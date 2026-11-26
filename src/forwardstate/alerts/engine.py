"""AlertEngine: rule evaluation, explainable alert content, lifecycle and replay (BRD p.8).

Notifies only. Nothing here sells, rebalances, routes orders or moves money (RISK-03). The
alternatives on an alert are options with estimated trade-offs, never instructions.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

import forwardstate
from forwardstate.contracts import (
    CASH_ID,
    ActionOption,
    Alert,
    AlertMetric,
    AlertRule,
    AlertSeverity,
    AlertStatus,
    AlertTransition,
    Confidence,
    DataOrigin,
    Event,
    EvidenceItem,
    Horizon,
    Portfolio,
    ReplayFrame,
    ReplayResult,
    RiskMetrics,
    ScenarioAssumptions,
    stable_hash,
)
from forwardstate.pit import NY, as_of_for_date, ensure_utc
from forwardstate.portfolio import (
    DataUnavailable,
    PortfolioEngine,
    Simulation,
    constraint_violations,
    move_to_cash,
    trading_cost,
)
from forwardstate.risk import prob_loss_exceeds, scenario_quantiles, var_cvar
from forwardstate.services import EventService, ForecastService, PointInTimeStore

from .rules import load_rules

MODEL_VERSION = f"{forwardstate.__version__}/al1"
UTC = timezone.utc

EVIDENCE_EVENT_DAYS = 10  # trading days of event evidence
EVENT_RULE_DAYS = 5  # trading days an event can trigger EVENT_SEVERITY
ANALYST_DAYS = 30  # calendar days of analyst evidence
EXPIRY_DAYS = 5  # trading days until an alert expires
MIN_HISTORY_DAYS = 60  # fewer trading days of prices -> confidence UNAVAILABLE
STALE_CALENDAR_DAYS = 7  # last close older than this -> data failure
PRICE_WINDOW_DAYS = 130  # calendar days of prices loaded per evaluation

# Lifecycle (RISK-05). SUPERSEDED is set by the engine only.
USER_TRANSITIONS = {
    AlertStatus.NEW: {AlertStatus.ACKNOWLEDGED, AlertStatus.RESOLVED},
    AlertStatus.ACKNOWLEDGED: {AlertStatus.RESOLVED},
    AlertStatus.RESOLVED: set(),
    AlertStatus.SUPERSEDED: set(),
}
OPEN = {AlertStatus.NEW, AlertStatus.ACKNOWLEDGED}

BASE_LIMITATIONS = [
    ("Probabilities and losses are simulated, not calibrated. They are not a forecast of what "
    "will happen."),
    ("Simulated paths resample past joint daily returns, so they assume the past is a fair "
    "guide; a new kind of shock may be worse."),
    "Confidence is LOW in the MVP: no model has been validated against outcomes.",
    "Events are shown as evidence of association, not proven cause.",
]


def local_date(ts: datetime) -> date:
    """The New York calendar date of an instant (as_of 23:59 NY is still that day)."""
    return ts.astimezone(NY).date()


@dataclass
class _Context:
    """Everything one evaluation needs, loaded once (point-in-time as of ``as_of``)."""

    as_of: datetime
    portfolio: Portfolio
    weights: dict[str, float]
    held: list[str]  # held securities, CASH excluded
    calendar: list[date]
    prices: pd.DataFrame  # wide adj_close, index = trading_date
    origins: set[str]
    n_paths: int
    sims: dict[Horizon, Simulation | str] = field(default_factory=dict)
    data_issues: list[str] = field(default_factory=list)
    recent_events: list[Event] | None = None

    def window_start(self, trading_days: int) -> date | None:
        if not self.calendar:
            return None
        return self.calendar[-min(trading_days, len(self.calendar))]

    @property
    def confidence(self) -> Confidence:
        return Confidence.LOW if len(self.calendar) >= MIN_HISTORY_DAYS else Confidence.UNAVAILABLE

    @property
    def origin(self) -> DataOrigin:
        if DataOrigin.SYNTHETIC.value in self.origins:
            return DataOrigin.SYNTHETIC
        if DataOrigin.DERIVED.value in self.origins:
            return DataOrigin.DERIVED
        return DataOrigin.REAL


class AlertEngine:
    """Implements ``forwardstate.services.AlertService``."""

    model_version = MODEL_VERSION

    def __init__(
        self,
        store: PointInTimeStore,
        forecaster: ForecastService,
        events: EventService,
        portfolio_engine: PortfolioEngine,
        rules: list[AlertRule] | None = None,
        persist_path: str | Path | None = None,
        n_paths: int = 2000,
        replay_n_paths: int = 500,
    ) -> None:
        self.store = store
        self.forecaster = forecaster
        self.events = events
        self.pe = portfolio_engine
        self._rules = list(rules) if rules is not None else load_rules()
        self.persist_path = Path(persist_path) if persist_path else None
        self.n_paths = n_paths
        self.replay_n_paths = replay_n_paths
        self._alerts: dict[str, Alert] = {}
        self._portfolio_of: dict[str, str] = {}
        self._transitions: list[AlertTransition] = []
        self.last_limitations: list[str] = []
        if self.persist_path and self.persist_path.exists():
            self._load()

    # ---- AlertService ---------------------------------------------------------------------
    def rules(self) -> list[AlertRule]:
        return list(self._rules)

    def set_rules(self, rules: list[AlertRule]) -> None:
        """Replace the rule set (e.g. after Settings change). Keeps the alert inbox."""
        self._rules = list(rules)

    def evaluate_alerts(
        self,
        portfolio: Portfolio,
        as_of: datetime,
        assumptions: ScenarioAssumptions,
        rule_ids: list[str] | None = None,
    ) -> list[Alert]:
        alerts, _ = self._evaluate(portfolio, as_of, assumptions, rule_ids, self.n_paths)
        self._save()
        return alerts

    def list_alerts(self, status: AlertStatus | None = None) -> list[Alert]:
        out = [a for a in self._alerts.values() if status is None or a.status == status]
        return sorted(out, key=lambda a: (a.as_of, a.rule_id, a.alert_id))

    def transitions(self, alert_id: str | None = None) -> list[AlertTransition]:
        return [t for t in self._transitions if alert_id is None or t.alert_id == alert_id]

    def transition(self, alert_id: str, to_status: AlertStatus, note: str | None = None) -> Alert:
        alert = self._alerts.get(alert_id)
        if alert is None:
            raise KeyError(f"Unknown alert_id {alert_id!r}.")
        to_status = AlertStatus(to_status)
        if to_status not in USER_TRANSITIONS[alert.status]:
            raise ValueError(
                f"Cannot move alert {alert_id} from {alert.status.value} to {to_status.value}."
            )
        updated = self._set_status(alert, to_status, datetime.now(UTC), note)
        self._save()
        return updated

    def replay(
        self,
        portfolio: Portfolio,
        start: date,
        end: date,
        assumptions: ScenarioAssumptions,
        step_trading_days: int = 1,
        rule_ids: list[str] | None = None,
    ) -> ReplayResult:
        """Walk forward day by day; each step sees only data available by that day's close.

        Runs on a fresh alert history so the same inputs always give the same result; the
        replay's alerts are then added to this engine's list (existing ones are kept as they are).
        """
        self._check_portfolio(portfolio)
        input_hash = stable_hash({
            "portfolio": portfolio, "start": start, "end": end, "assumptions": assumptions,
            "step": step_trading_days, "rule_ids": rule_ids, "rules": self._rules,
            "n_paths": self.replay_n_paths, "model_version": MODEL_VERSION,
        })
        sub = AlertEngine(self.store, self.forecaster, self.events, self.pe, self._rules,
                          n_paths=self.replay_n_paths, replay_n_paths=self.replay_n_paths)
        risky = [h.security_id for h in portfolio.holdings if h.security_id != CASH_ID]
        cal_ids = risky or [s for s in self.pe.universe() if s != CASH_ID]
        p = self.store.prices(cal_ids, as_of_for_date(end), start=start, end=end)
        days = sorted({d.date() for d in pd.to_datetime(p["trading_date"])})
        steps = days[::step_trading_days]
        weights = {h.security_id: h.weight for h in portfolio.holdings}
        cash_daily = portfolio.constraints.cash_annual_yield / 252

        frames: list[ReplayFrame] = []
        for day in steps:
            as_of = as_of_for_date(day)
            new, ctx = sub._evaluate(portfolio, as_of, assumptions, rule_ids, self.replay_n_paths)
            metrics = sub._metrics(ctx, assumptions, Horizon.SHORT)
            value = self._mark_to_market(portfolio, weights, risky, days[0], day, as_of,
                                         cash_daily, days.index(day))
            frames.append(ReplayFrame(as_of=day, portfolio_value=value, metrics=metrics,
                                      new_alert_ids=[a.alert_id for a in new]))
        alerts = sub.list_alerts()
        for a in alerts:
            if a.alert_id not in self._alerts:
                self._alerts[a.alert_id] = a
                self._portfolio_of[a.alert_id] = portfolio.portfolio_id
        self._transitions.extend(
            t for t in sub._transitions if t not in self._transitions
        )
        self._save()
        return ReplayResult(
            run_id=f"replay-{input_hash[:12]}", start=start, end=end, frames=frames,
            alerts=alerts, model_version=MODEL_VERSION, input_hash=input_hash,
        )

    # ---- evaluation -------------------------------------------------------------------------
    def _check_portfolio(self, portfolio: Portfolio) -> None:
        bad = [i for i in self.pe.feasibility(portfolio)
               if i.code in {"unknown_security", "not_investable", "duplicate_security",
                             "weights_sum"}]
        if bad:
            raise ValueError("Portfolio cannot be assessed: " + " ".join(i.message for i in bad))

    def _evaluate(
        self,
        portfolio: Portfolio,
        as_of: datetime,
        assumptions: ScenarioAssumptions,
        rule_ids: list[str] | None,
        n_paths: int,
    ) -> tuple[list[Alert], _Context]:
        as_of = ensure_utc(as_of)
        self._check_portfolio(portfolio)
        ctx = self._context(portfolio, as_of, n_paths)
        run_id = "alerts-" + stable_hash({
            "portfolio": portfolio, "as_of": as_of, "assumptions": assumptions,
            "rule_ids": rule_ids, "n_paths": n_paths, "model_version": MODEL_VERSION,
        })[:12]
        rules = [r for r in self._rules if r.enabled and (rule_ids is None or r.rule_id in rule_ids)]
        triggered = []
        for rule in rules:
            hit = self._check_rule(rule, ctx, assumptions)
            if hit is not None:
                triggered.append((rule, *hit))
        out = []
        for rule, value, affected, event_ids in triggered:
            alert = self._raise(rule, value, affected, event_ids, ctx, assumptions, run_id)
            if alert is not None:
                out.append(alert)
        self.last_limitations = list(ctx.data_issues)
        return out, ctx

    def _context(self, portfolio: Portfolio, as_of: datetime, n_paths: int) -> _Context:
        weights = {h.security_id: h.weight for h in portfolio.holdings}
        held = [s for s, w in weights.items() if s != CASH_ID and w > 0]
        lookbacks = [r.lookback_trading_days or 0 for r in self._rules]
        span = max(PRICE_WINDOW_DAYS, 2 * max(lookbacks, default=0) + 30)
        cal_ids = held or [s for s in self.pe.universe() if s != CASH_ID]
        issues: list[str] = []
        try:
            p = self.store.prices(cal_ids, as_of, start=local_date(as_of) - timedelta(days=span))
        except Exception as exc:  # noqa: BLE001 - any source failure is reported as a data issue
            p = pd.DataFrame(columns=["security_id", "trading_date", "adj_close", "origin"])
            issues.append(f"Price data could not be read ({exc}).")
        wide = (p.pivot(index="trading_date", columns="security_id", values="adj_close")
                .sort_index() if len(p) else pd.DataFrame())
        missing = [s for s in cal_ids if s not in wide.columns]
        if missing:
            issues.append(f"No price data for {', '.join(missing)} as of {local_date(as_of)}.")
        calendar = [d.date() for d in wide.index]
        if calendar and (local_date(as_of) - calendar[-1]).days > STALE_CALENDAR_DAYS:
            issues.append(f"Prices are stale: the last close is {calendar[-1]}.")
        return _Context(as_of, portfolio, weights, held, calendar, wide,
                        set(p["origin"].unique()) if len(p) else set(), n_paths,
                        data_issues=issues)

    def _sim(self, ctx: _Context, assumptions: ScenarioAssumptions,
             horizon: Horizon) -> Simulation | None:
        if horizon not in ctx.sims:
            try:
                ctx.sims[horizon] = self.pe.simulate(
                    self.pe.universe(), ctx.as_of, horizon, assumptions,
                    ctx.portfolio.constraints.cash_annual_yield, n_paths=ctx.n_paths,
                )
            except DataUnavailable as exc:
                ctx.sims[horizon] = str(exc)
                ctx.data_issues.append(
                    f"{horizon.value.title()}-horizon risk could not be simulated: {exc}"
                )
        s = ctx.sims[horizon]
        return s if isinstance(s, Simulation) else None

    def _metrics(self, ctx: _Context, assumptions: ScenarioAssumptions,
                 horizon: Horizon) -> RiskMetrics | None:
        sim = self._sim(ctx, assumptions, horizon)
        return sim.metrics(ctx.weights) if sim else None

    def _events_window(self, ctx: _Context, trading_days: int) -> list[Event]:
        start = ctx.window_start(trading_days)
        if start is None or not ctx.held:
            return []
        try:
            evs = self.events.list_events(ctx.as_of, ctx.held, start=start, end=local_date(ctx.as_of))
        except Exception as exc:  # noqa: BLE001 - any source failure is reported as a data issue
            ctx.data_issues.append(f"Events could not be read ({exc}).")
            return []
        return [e for e in evs if e.canonical_event_id is None]

    def _check_rule(
        self, rule: AlertRule, ctx: _Context, assumptions: ScenarioAssumptions
    ) -> tuple[float, list[str], list[str]] | None:
        """(metric value, affected ids, triggering event ids) when the rule fires, else None."""
        m = rule.metric
        if m == AlertMetric.CONCENTRATION:
            risky = {s: w for s, w in ctx.weights.items() if s != CASH_ID}
            if not risky:
                return None
            top = max(sorted(risky), key=lambda s: risky[s])
            return (risky[top], [top], []) if risky[top] > rule.threshold else None

        if m == AlertMetric.REALIZED_LOSS:
            value = self._realized_loss(ctx, rule.lookback_trading_days or 5)
            if value is None:
                ctx.data_issues.append(
                    f"Rule '{rule.rule_id}' skipped: not enough recent prices to measure the "
                    "realized loss."
                )
                return None
            return (value, list(ctx.held), []) if value > rule.threshold else None

        if m == AlertMetric.EVENT_SEVERITY:
            evs = self._events_window(ctx, EVENT_RULE_DAYS)
            worst, affected, ids = 0.0, set(), set()
            for e in evs:
                try:
                    imps = self.events.impact_estimates(ctx.as_of, event_id=e.event_id)
                except Exception as exc:  # noqa: BLE001 - any source failure is reported as a data issue
                    ctx.data_issues.append(f"Impact estimates could not be read ({exc}).")
                    return None
                for imp in imps:
                    if (not imp.realized or imp.abnormal_return is None
                            or imp.security_id not in ctx.held):
                        continue
                    if abs(imp.abnormal_return) > rule.threshold:
                        worst = max(worst, abs(imp.abnormal_return))
                        affected.add(imp.security_id)
                        ids.add(e.event_id)
            return (worst, sorted(affected), sorted(ids)) if ids else None

        sim = self._sim(ctx, assumptions, rule.horizon)
        if sim is None:
            return None  # data failure already noted; never a false alert
        r = sim.portfolio_returns(ctx.weights)
        if m == AlertMetric.FORECAST_DRAWDOWN:
            value = var_cvar(r)[1]
        elif m == AlertMetric.DOWNSIDE_PROBABILITY:
            value = prob_loss_exceeds(r, rule.loss_level if rule.loss_level is not None else 0.05)
        else:  # pragma: no cover - enum is exhaustive
            return None
        return (value, list(ctx.held), []) if value > rule.threshold else None

    def _realized_loss(self, ctx: _Context, lookback: int) -> float | None:
        if not ctx.held:
            return 0.0
        w = ctx.prices
        if len(w) < lookback + 1 or any(s not in w.columns for s in ctx.held):
            return None
        window = w[ctx.held].iloc[-(lookback + 1):]
        if window.isna().any().any():
            return None
        growth = window.iloc[-1] / window.iloc[0] - 1.0
        cash = ctx.weights.get(CASH_ID, 0.0)
        y = ctx.portfolio.constraints.cash_annual_yield
        ret = float(sum(ctx.weights[s] * growth[s] for s in ctx.held)) + cash * y * lookback / 252
        return -ret

    # ---- alert content --------------------------------------------------------------------
    def _raise(
        self,
        rule: AlertRule,
        value: float,
        affected: list[str],
        event_ids: list[str],
        ctx: _Context,
        assumptions: ScenarioAssumptions,
        run_id: str,
    ) -> Alert | None:
        pid = ctx.portfolio.portfolio_id
        # Every input that changes the alert's content is in its id, so a cached alert is only
        # returned for truly identical inputs (rule incl. threshold, assumptions, paths).
        alert_id = stable_hash([rule, ctx.as_of, ctx.portfolio, assumptions, ctx.n_paths])[:16]
        if alert_id in self._alerts:
            return self._alerts[alert_id]  # same inputs -> same alert
        prev = self._latest(rule.rule_id, pid, before=ctx.as_of)
        if prev is not None and self._trading_days(prev.as_of, ctx) < rule.cooldown_trading_days:
            return None  # cooldown: no new alert for the same rule
        alert = self._build(alert_id, rule, value, affected, event_ids, ctx, assumptions, run_id)
        self._alerts[alert_id] = alert
        self._portfolio_of[alert_id] = pid
        for old in list(self._alerts.values()):
            if (old.alert_id != alert_id and old.rule_id == rule.rule_id
                    and self._portfolio_of.get(old.alert_id) == pid and old.status in OPEN
                    and old.as_of <= alert.as_of):
                self._set_status(old, AlertStatus.SUPERSEDED, alert.as_of,
                                 f"Superseded by {alert_id}", superseded_by=alert_id)
        return alert

    def _build(
        self,
        alert_id: str,
        rule: AlertRule,
        value: float,
        affected: list[str],
        event_ids: list[str],
        ctx: _Context,
        assumptions: ScenarioAssumptions,
        run_id: str,
    ) -> Alert:
        c = ctx.portfolio.constraints
        total = ctx.portfolio.total_value
        sim = self._sim(ctx, assumptions, rule.horizon)
        days = self.pe.horizon_days[rule.horizon]
        limitations = list(BASE_LIMITATIONS)
        limitations.append(
            f"Cash is assumed to earn {c.cash_annual_yield:.2%} a year with no price movement "
            "(constraints.cash_annual_yield); real cash equivalents still carry some risk."
        )
        if ctx.origin == DataOrigin.SYNTHETIC:
            limitations.append("Built on SYNTHETIC fixture data, not real market history.")
        limitations += ctx.data_issues

        projected_loss = projected_pct = probability = None
        alternatives: list[ActionOption] = []
        loss_level = rule.loss_level if rule.loss_level is not None else 0.05
        if sim is not None:
            r = sim.portfolio_returns(ctx.weights)
            pess = scenario_quantiles(r)["pessimistic"]
            projected_pct = max(0.0, -pess)
            projected_loss = projected_pct * total
            probability = prob_loss_exceeds(r, loss_level)
            limitations.append(
                f"'probability' is the share of {len(r)} simulated {days}-day paths losing more "
                f"than {loss_level:.0%} (simulated, not calibrated). 'projected_loss' is the "
                "pessimistic (10th percentile) simulated outcome."
            )
            alternatives = self._alternatives(sim, ctx)
        else:
            limitations.append("No simulated loss or probability: the simulation could not run.")

        title, summary = self._text(rule, value, affected, ctx, days, projected_loss,
                                    projected_pct, event_ids)
        try:
            severity = AlertSeverity(rule.severity)
        except ValueError:
            severity = AlertSeverity.WARNING
        expiry = pd.Timestamp(local_date(ctx.as_of)) + pd.offsets.BDay(EXPIRY_DAYS)
        return Alert(
            portfolio_id=ctx.portfolio.portfolio_id,
            alert_id=alert_id,
            run_id=run_id,
            rule_id=rule.rule_id,
            rule_version=rule.version,
            severity=severity,
            as_of=ctx.as_of,
            horizon=rule.horizon,
            horizon_trading_days=days,
            title=title,
            summary=summary,
            triggering_event_ids=event_ids,
            affected_security_ids=affected,
            current_exposure={k: v for k, v in ctx.weights.items() if v > 0},
            metric_value=float(value),
            threshold=rule.threshold,
            projected_loss=projected_loss,
            projected_loss_pct=projected_pct,
            probability=probability,
            confidence=ctx.confidence if sim is not None else Confidence.UNAVAILABLE,
            limitations=limitations,
            evidence=self._evidence(ctx, sim, days),
            alternatives=alternatives,
            expires_at=as_of_for_date(expiry.date()),
        )

    def _text(self, rule, value, affected, ctx, days, loss, pct, event_ids) -> tuple[str, str]:
        tail = (f" In the pessimistic simulated case the portfolio would lose about "
                f"${loss:,.0f} ({pct:.1%}) over {days} trading days." if loss is not None else "")
        m = rule.metric
        if m == AlertMetric.FORECAST_DRAWDOWN:
            return (f"Simulated {days}-day loss risk above {rule.threshold:.0%}",
                    (f"In the worst 5% of simulated {days}-day outcomes the portfolio loses "
                    f"{value:.1%} on average (CVaR 95), above your {rule.threshold:.1%} alert "
                    f"level. This is a forecast, not a realized loss.{tail}"))
        if m == AlertMetric.DOWNSIDE_PROBABILITY:
            lvl = rule.loss_level if rule.loss_level is not None else 0.05
            return (f"Simulated chance of a {lvl:.0%}+ loss is {value:.0%}",
                    (f"In {value:.0%} of simulated {days}-day outcomes the portfolio loses more "
                    f"than {lvl:.0%}, above your {rule.threshold:.0%} alert level. Simulated, "
                    f"not calibrated.{tail}"))
        if m == AlertMetric.REALIZED_LOSS:
            lb = rule.lookback_trading_days or 5
            return (f"Portfolio fell {value:.1%} in the last {lb} trading days",
                    (f"Measured from prices: the held portfolio lost {value:.1%} over the last "
                    f"{lb} trading days, above your {rule.threshold:.1%} alert level. This is a "
                    f"realized change, not a forecast.{tail}"))
        if m == AlertMetric.CONCENTRATION:
            top = affected[0] if affected else "One position"
            return (f"{top} is {value:.0%} of the portfolio",
                    (f"{top} is {value:.1%} of the portfolio, above your {rule.threshold:.0%} "
                    f"concentration alert level.{tail}"))
        return (f"Large event-linked move on {', '.join(affected)}",
                (f"An event in the last {EVENT_RULE_DAYS} trading days "
                f"({', '.join(event_ids)}) is linked to a benchmark-adjusted move of "
                f"{value:.1%} on {', '.join(affected)}, above your {rule.threshold:.1%} alert "
                f"level. Association, not proven cause.{tail}"))

    def _alternatives(self, sim: Simulation, ctx: _Context) -> list[ActionOption]:
        c = ctx.portfolio.constraints
        total = ctx.portfolio.total_value
        hold = ctx.weights
        hold_opt = scenario_quantiles(sim.portfolio_returns(hold))["optimistic"]
        out = []
        for label, w in (("Hold (no change)", dict(hold)),
                         ("Move 25% to cash", move_to_cash(hold, 0.25)),
                         ("Move 50% to cash", move_to_cash(hold, 0.50))):
            r = sim.portfolio_returns(w)
            q = scenario_quantiles(r)
            note = "An option with estimated trade-offs, not an instruction."
            broken = constraint_violations(w, c, hold)
            if broken:
                note += " Note: " + "; ".join(broken) + "."
            out.append(ActionOption(
                label=label,
                weights={k: v for k, v in w.items() if v > 1e-12},
                expected_return=float(r.mean()),
                cvar_95=var_cvar(r)[1],
                projected_loss=max(0.0, -q["pessimistic"]) * total,
                est_cost=trading_cost(w, hold, total, c.transaction_cost_bps),
                missed_upside=max(0.0, hold_opt - q["optimistic"]) * total,  # currency, like projected_loss
                note=note,
            ))
        return out

    def _evidence(self, ctx: _Context, sim: Simulation | None, days: int) -> list[EvidenceItem]:
        items: list[EvidenceItem] = []
        for e in self._events_window(ctx, EVIDENCE_EVENT_DAYS):
            when = e.occurred_at or e.scheduled_at or e.available_at
            status = e.status.value
            items.append(EvidenceItem(
                kind="event", ref_id=e.event_id, label=f"{e.title} ({status}, {local_date(when)})",
                at=when, origin=e.origin,
                url=next((s for s in e.source_ids if s.startswith("http")), None),
            ))
        if ctx.held:
            cutoff = ctx.as_of - timedelta(days=ANALYST_DAYS)
            try:
                obs = self.store.analyst_observations(ctx.as_of, ctx.held)
            except Exception as exc:  # noqa: BLE001 - any source failure is reported as a data issue
                ctx.data_issues.append(f"Analyst data could not be read ({exc}).")
                obs = []
            for o in obs:
                if o.issued_at >= cutoff:
                    target = f", target {o.target_price:g}" if o.target_price else ""
                    items.append(EvidenceItem(
                        kind="analyst", ref_id=o.observation_id,
                        label=f"{o.analyst_source}: {o.action.value} {o.security_id}"
                        f"{target} (analyst view, not fact)",
                        at=o.issued_at, origin=o.origin,
                    ))
        start = ctx.window_start(EVIDENCE_EVENT_DAYS)
        if start is not None and ctx.held:
            win = ctx.prices.loc[pd.Timestamp(start):, [s for s in ctx.held
                                                        if s in ctx.prices.columns]]
            if len(win) >= 2:
                moves = win.iloc[-1] / win.iloc[0] - 1.0
                text = ", ".join(f"{s} {moves[s]:+.1%}" for s in win.columns
                                 if np.isfinite(moves[s]))
                end = win.index[-1].date()
                items.append(EvidenceItem(
                    kind="price", ref_id=f"price:{start}:{end}",
                    label=f"Price moves {start} to {end}: {text}",
                    at=as_of_for_date(end), origin=ctx.origin,
                ))
        if sim is not None:
            items.append(EvidenceItem(
                kind="model", ref_id=f"sim:{self.pe.model_version}:{days}d",
                label=f"{sim.paths.shape[0]} simulated joint {days}-day paths "
                "(correlations kept); simulated, not calibrated",
                at=ctx.as_of, origin=DataOrigin.DERIVED,
            ))
        return items

    # ---- lifecycle ------------------------------------------------------------------------
    def _latest(self, rule_id: str, portfolio_id: str, before: datetime) -> Alert | None:
        """Most recent alert for this rule and portfolio strictly before ``before``.
        Alerts dated later must never influence an earlier as-of (no look-ahead via state)."""
        same = [a for a in self._alerts.values()
                if a.rule_id == rule_id and self._portfolio_of.get(a.alert_id) == portfolio_id
                and a.as_of < before]
        return max(same, key=lambda a: a.as_of) if same else None

    def _trading_days(self, prev: datetime, ctx: _Context) -> int:
        a, b = sorted([local_date(prev), local_date(ctx.as_of)])
        in_cal = [d for d in ctx.calendar if a < d <= b]
        if ctx.calendar and a >= ctx.calendar[0]:
            return len(in_cal)
        return len(pd.bdate_range(a + timedelta(days=1), b))

    def _set_status(self, alert: Alert, to: AlertStatus, at: datetime, note: str | None,
                    superseded_by: str | None = None) -> Alert:
        update: dict = {"status": to}
        if superseded_by:
            update["superseded_by"] = superseded_by
        new = alert.model_copy(update=update)
        self._alerts[alert.alert_id] = new
        self._transitions.append(AlertTransition(
            alert_id=alert.alert_id, from_status=alert.status, to_status=to, at=at, note=note
        ))
        return new

    # ---- replay helpers -----------------------------------------------------------------
    def _mark_to_market(self, portfolio: Portfolio, weights: dict[str, float], risky: list[str],
                        day0: date, day: date, as_of: datetime, cash_daily: float,
                        k: int) -> float:
        """Value of the held (no-change, buy-and-hold) portfolio on ``day``."""
        value = weights.get(CASH_ID, 0.0) * (1 + cash_daily) ** k
        if risky:
            p = self.store.prices(risky, as_of, start=day0, end=day)
            wide = p.pivot(index="trading_date", columns="security_id", values="adj_close")
            for s in risky:
                col = wide[s].dropna() if s in wide.columns else pd.Series(dtype=float)
                if len(col):
                    value += weights[s] * float(col.iloc[-1] / col.iloc[0])
                else:
                    value += weights[s]  # no price yet: carried at cost
        return float(portfolio.total_value * value)

    # ---- persistence ----------------------------------------------------------------------
    def _save(self) -> None:
        if not self.persist_path:
            return
        data = {
            "alerts": [a.model_dump(mode="json") for a in self._alerts.values()],
            "portfolio_of": self._portfolio_of,
            "transitions": [t.model_dump(mode="json") for t in self._transitions],
        }
        self.persist_path.parent.mkdir(parents=True, exist_ok=True)
        self.persist_path.write_text(json.dumps(data, indent=1, sort_keys=True))

    def _load(self) -> None:
        data = json.loads(self.persist_path.read_text())
        for a in data.get("alerts", []):
            alert = Alert.model_validate(a)
            self._alerts[alert.alert_id] = alert
        self._portfolio_of.update(data.get("portfolio_of", {}))
        self._transitions = [AlertTransition.model_validate(t) for t in data.get("transitions", [])]


__all__ = ["MODEL_VERSION", "AlertEngine"]

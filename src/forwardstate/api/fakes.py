"""TEST-ONLY fake engines that implement the service Protocols.

DO NOT USE IN PRODUCTION. ``build_services`` never uses these. They exist so the API can be
tested (and the frontend developed) before the real engines land. Every number they produce is
labelled ``method="fake-test-only"`` and is not a forecast.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

import numpy as np
import pandas as pd

from forwardstate.contracts import (
    CASH_ID,
    DEFAULT_HORIZON_DAYS,
    Alert,
    AlertMetric,
    AlertRule,
    AlertSeverity,
    AlertStatus,
    Allocation,
    Confidence,
    Direction,
    Event,
    EventClass,
    FeasibilityIssue,
    ForecastRun,
    Horizon,
    ImpactEstimate,
    Portfolio,
    PortfolioEvaluation,
    ReplayFrame,
    ReplayResult,
    RiskMetrics,
    ScenarioAssumptions,
    ScenarioForecast,
    ScenarioName,
    Security,
    SecurityForecast,
    stable_hash,
)
from forwardstate.pit import as_of_for_date, ensure_utc
from forwardstate.services import PointInTimeStore

FAKE = "fake-test-only"


class FakeSector:
    sector_id = "financials"

    def __init__(self, store: PointInTimeStore) -> None:
        self._store = store

    def universe(self) -> list[Security]:
        return [s for s in self._store.securities("financials") if s.role.value in ("focal", "peer")]

    def benchmarks(self) -> list[Security]:
        return [s for s in self._store.securities("financials") if s.role.value == "benchmark"]

    def event_taxonomy(self) -> dict[EventClass, list[str]]:
        return {c: [] for c in EventClass}

    def indicators(self) -> list[str]:
        return ["DFF", "DGS2", "DGS10"]

    def exposure(self, event: Event, security_ids: list[str]) -> dict[str, float]:
        return {s: 1.0 if s in event.affected_security_ids else 0.0 for s in security_ids}


class FakeEvents:
    def __init__(self, store: PointInTimeStore) -> None:
        self.store = store

    def list_events(self, as_of, security_ids=None, event_classes=None, start=None, end=None):
        return self.store.events(as_of, security_ids, event_classes, start, end)

    def impact_estimates(self, as_of, event_id=None, security_id=None):
        out = []
        for e in self.store.events(as_of):
            if event_id and e.event_id != event_id:
                continue
            for sid in e.affected_security_ids:
                if security_id and sid != security_id:
                    continue
                out.append(ImpactEstimate(
                    event_id=e.event_id, security_id=sid, realized=False, window_pre_days=1,
                    window_post_days=5, direction=Direction.UNKNOWN, method=FAKE,
                    confidence=Confidence.UNAVAILABLE, as_of=ensure_utc(as_of),
                    note="Fake engine: no estimate.",
                ))
        return out


def _last_prices(store: PointInTimeStore, ids: list[str], as_of: datetime) -> dict[str, float]:
    df = store.prices(ids, as_of)
    if df.empty:
        return {}
    return df.groupby("security_id")["adj_close"].last().astype(float).to_dict()


class FakeForecaster:
    model_version = "fake-forecast-0"

    def __init__(self, store: PointInTimeStore) -> None:
        self.store = store

    def forecast(self, as_of, security_ids, horizons, assumptions):
        as_of = ensure_utc(as_of)
        last = _last_prices(self.store, security_ids, as_of)
        fcs = []
        for sid in security_ids:
            for h in horizons:
                p0 = last.get(sid)
                if p0 is None:
                    fcs.append(SecurityForecast(
                        security_id=sid, horizon=h, horizon_trading_days=DEFAULT_HORIZON_DAYS[h],
                        start_price=None, status=Confidence.UNAVAILABLE,
                        status_reason="no prices", method=FAKE, model_version=self.model_version,
                    ))
                    continue
                scen = [
                    ScenarioForecast(
                        scenario=name, quantile=q, projected_return=r, projected_price=p0 * (1 + r),
                        interval_low=p0 * 0.8, interval_high=p0 * 1.2, interval_coverage=0.8,
                    )
                    for name, q, r in (
                        (ScenarioName.PESSIMISTIC, 0.1, -0.1),
                        (ScenarioName.BASE, 0.5, 0.0),
                        (ScenarioName.OPTIMISTIC, 0.9, 0.1),
                    )
                ]
                fcs.append(SecurityForecast(
                    security_id=sid, horizon=h, horizon_trading_days=DEFAULT_HORIZON_DAYS[h],
                    start_price=p0, scenarios=scen, status=Confidence.LOW, method=FAKE,
                    model_version=self.model_version,
                ))
        return ForecastRun(
            run_id=uuid.uuid4().hex, as_of=as_of, data_cutoff=min(self.store.latest_as_of(), as_of),
            security_ids=security_ids, horizons=horizons, assumptions=assumptions, forecasts=fcs,
            model_version=self.model_version,
            input_hash=stable_hash([as_of, security_ids, horizons, assumptions]),
            created_at=datetime.now(timezone.utc),
        )

    def simulate_joint_returns(self, as_of, security_ids, horizon_days, assumptions,
                               n_paths=2000, seed=0):
        return np.zeros((n_paths, horizon_days, len(security_ids)))


class FakePortfolio:
    model_version = "fake-portfolio-0"

    def __init__(self, store: PointInTimeStore) -> None:
        self.store = store

    def _metrics(self, p: Portfolio) -> RiskMetrics:
        w = {h.security_id: h.weight for h in p.holdings}
        top = max(w, key=w.get) if w else None
        return RiskMetrics(
            horizon=p.horizon, horizon_trading_days=DEFAULT_HORIZON_DAYS[p.horizon],
            expected_return=0.0, volatility=0.0, var_95=0.0, cvar_95=0.0, max_drawdown_est=0.0,
            concentration_hhi=float(sum(x * x for x in w.values())), largest_position=top,
            largest_weight=w.get(top, 0.0) if top else 0.0, cash_weight=w.get(CASH_ID, 0.0),
        )

    def evaluate_portfolio(self, portfolio, as_of, assumptions):
        as_of = ensure_utc(as_of)
        total = sum(h.weight for h in portfolio.holdings)
        known = {s.security_id for s in self.store.securities()}
        issues = []
        if abs(total - 1) > 1e-6:
            issues.append(FeasibilityIssue(code="weights_sum", message=f"Weights sum to {total}"))
        for h in portfolio.holdings:
            if h.security_id not in known:
                issues.append(FeasibilityIssue(code="unknown_security", message=h.security_id))
        weights = {h.security_id: h.weight for h in portfolio.holdings}
        current = None if issues else Allocation(
            label="current", weights=weights, metrics=self._metrics(portfolio), notes=[FAKE]
        )
        return PortfolioEvaluation(
            run_id="", as_of=as_of, portfolio_id=portfolio.portfolio_id, feasible=not issues,
            issues=issues, current=current,
            candidates=[current.model_copy(update={"label": "no change"})] if current else [],
            model_version=self.model_version,
            input_hash=stable_hash([as_of, portfolio, assumptions]),
        )

    def optimize(self, portfolio, as_of, assumptions):
        return self.evaluate_portfolio(portfolio, as_of, assumptions)


class FakeAlerts:
    """Only the CONCENTRATION metric fires; other rules never trigger in the fake."""

    model_version = "fake-alerts-0"

    def __init__(self, store: PointInTimeStore, rules: list[AlertRule]) -> None:
        self.store = store
        self._rules = list(rules)
        self._inbox: dict[str, Alert] = {}

    def rules(self) -> list[AlertRule]:
        return list(self._rules)

    def set_rules(self, rules: list[AlertRule]) -> None:
        self._rules = list(rules)

    def _evaluate(self, portfolio: Portfolio, as_of: datetime, rule_ids, run_id: str) -> list[Alert]:
        out = []
        weights = {h.security_id: h.weight for h in portfolio.holdings if h.security_id != CASH_ID}
        for r in self._rules:
            if not r.enabled or (rule_ids and r.rule_id not in rule_ids):
                continue
            if r.metric != AlertMetric.CONCENTRATION or not weights:
                continue
            top = max(weights, key=weights.get)
            if weights[top] <= r.threshold:
                continue
            aid = stable_hash([r.rule_id, r.version, as_of, portfolio])[:16]
            out.append(Alert(
                alert_id=aid, run_id=run_id, rule_id=r.rule_id, rule_version=r.version,
                severity=AlertSeverity(r.severity), as_of=as_of, horizon=r.horizon,
                horizon_trading_days=DEFAULT_HORIZON_DAYS[r.horizon],
                title=f"{top} is {weights[top]:.0%} of the portfolio",
                summary="Fake engine alert.", affected_security_ids=[top],
                metric_value=weights[top], threshold=r.threshold, confidence=Confidence.LOW,
                limitations=[FAKE],
            ))
        return out

    def evaluate_alerts(self, portfolio, as_of, assumptions, rule_ids=None):
        alerts = self._evaluate(portfolio, ensure_utc(as_of), rule_ids, uuid.uuid4().hex)
        for a in alerts:
            self._inbox[a.alert_id] = a
        return alerts

    def list_alerts(self, status: AlertStatus | None = None) -> list[Alert]:
        return [a for a in self._inbox.values() if status is None or a.status == status]

    def transition(self, alert_id, to_status, note=None):
        a = self._inbox[alert_id]  # KeyError -> 404
        if a.status in (AlertStatus.RESOLVED, AlertStatus.SUPERSEDED):
            raise ValueError(f"Alert is {a.status.value}; it cannot move to {to_status.value}.")
        a = a.model_copy(update={"status": to_status})
        self._inbox[alert_id] = a
        return a

    def replay(self, portfolio, start: date, end: date, assumptions: ScenarioAssumptions,
               step_trading_days=1, rule_ids=None):
        run_id = uuid.uuid4().hex
        ids = [h.security_id for h in portfolio.holdings if h.security_id != CASH_ID]
        df = self.store.prices(ids, as_of_for_date(end), start, end)
        wide = df.pivot(index="trading_date", columns="security_id", values="adj_close").sort_index()
        frames, alerts = [], []
        for d in list(wide.index)[::step_trading_days]:
            d = pd.Timestamp(d).date()
            row = wide.loc[pd.Timestamp(d)] / wide.iloc[0]
            value = portfolio.total_value * sum(
                h.weight * (float(row[h.security_id]) if h.security_id in row else 1.0)
                for h in portfolio.holdings
            )
            new = self._evaluate(portfolio, as_of_for_date(d), rule_ids, run_id)
            alerts += new
            frames.append(ReplayFrame(as_of=d, portfolio_value=value,
                                      new_alert_ids=[a.alert_id for a in new]))
        return ReplayResult(
            run_id=run_id, start=start, end=end, frames=frames, alerts=alerts,
            model_version=self.model_version,
            input_hash=stable_hash([portfolio, start, end, assumptions, step_trading_days]),
        )


def fake_services(store: PointInTimeStore | None = None, rules: list[AlertRule] | None = None):
    """TEST-ONLY: FixtureStore + fake engines, labelled synthetic."""
    from forwardstate.contracts import DataOrigin
    from forwardstate.testing import FixtureStore

    from .container import Services

    store = store or FixtureStore()
    return Services(
        store=store, events=FakeEvents(store), forecaster=FakeForecaster(store),
        portfolio=FakePortfolio(store), alerts=FakeAlerts(store, rules or []),
        data_origin=DataOrigin.SYNTHETIC, sector=FakeSector(store),
    )


__all__ = [
    "FakeAlerts",
    "FakeEvents",
    "FakeForecaster",
    "FakePortfolio",
    "FakeSector",
    "Horizon",
    "fake_services",
]

"""ForecastEngine: scenario forecasts and correlated joint return paths (implements
``ForecastService``, FC-01..05, PF-03).

Method ``block-bootstrap+blended-drift v1``:
1. Take daily returns over ``assumptions.lookback_years`` (point-in-time, as of ``as_of``).
2. Stationary block bootstrap (mean block 5 days) of whole rows, so cross-asset correlation
   is kept.
3. Replace each asset's historical mean with a transparent blended drift and scale the
   demeaned returns by ``volatility_multiplier``.
4. Scenarios are the 0.9 / 0.5 / 0.1 quantiles of the simulated horizon return.
Nothing is calibrated, so ``probability`` stays None and status is never HIGH.
"""

from __future__ import annotations

import math
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

import forwardstate
from forwardstate.contracts import (
    CASH_ID,
    DEFAULT_HORIZON_DAYS,
    Confidence,
    CorporateActionKind,
    EventClass,
    ForecastRun,
    Horizon,
    ScenarioAssumptions,
    ScenarioForecast,
    ScenarioName,
    SecurityForecast,
    stable_hash,
)
from forwardstate.features import build_feature_snapshot
from forwardstate.industries import get_sector
from forwardstate.pit import adjust_closes, ensure_utc

from .bootstrap import MEAN_BLOCK_LENGTH, seed_from_hash, stationary_bootstrap_indices

METHOD = "block-bootstrap+blended-drift v1"
MODEL_VERSION = f"{forwardstate.__version__}/fc1"

MARKET_ID = "SPY"
TRADING_DAYS_YEAR = 252
MIN_SIM_DAYS = 60  # simulate_joint_returns refuses shorter joint histories
MIN_FORECAST_DAYS = 250  # fewer -> UNAVAILABLE
MEDIUM_FORECAST_DAYS = 750  # fewer -> LOW
HIST_SHRINK = 0.5  # historical mean shrunk 50% toward beta x market mean
RATE_T_MIN = 1.0  # |t| below this -> sector default rate sensitivity
SECTOR_RATE_DEFAULT_PER_25BPS = 0.004  # banks: +0.4% price return per +25 bps (documented prior)
EARNINGS_MIN_SAMPLES = 6
ANALYST_HORIZON_DAYS = 252  # analyst targets are 12-month views; never prorated beyond that
FORECAST_PATHS = 2000
QUANTILES = {ScenarioName.OPTIMISTIC: 0.9, ScenarioName.BASE: 0.5, ScenarioName.PESSIMISTIC: 0.1}
INTERVAL = (0.1, 0.9)
NOTE = "Association, not proven causation; scenarios are not price targets."


@dataclass
class _History:
    rets: pd.DataFrame  # joint rows (no NaN) of non-cash ids + SPY, lookback window
    mu: pd.Series
    beta: pd.Series
    mu_market: float
    counts: dict[str, int]  # per-security non-NaN days in the lookback window


def price_returns(store, ids: list[str], as_of) -> pd.DataFrame:
    """Daily *price* returns (split-adjusted, dividends excluded) as of ``as_of``.

    Forecasts are labelled price returns and applied to the raw start price, and analyst
    targets are price targets, so dividends must not inflate the drift.
    """
    p = store.prices(ids, as_of)
    if p.empty:
        return pd.DataFrame(columns=ids)
    splits = [a for a in store.corporate_actions(ids, as_of) if a.kind == CorporateActionKind.SPLIT]
    p = p.assign(px=adjust_closes(p[["security_id", "trading_date", "raw_close"]], splits, as_of))
    wide = p.pivot(index="trading_date", columns="security_id", values="px").sort_index()
    return wide.pct_change(fill_method=None).iloc[1:]


class ForecastEngine:
    """Implements ``forwardstate.services.ForecastService``."""

    def __init__(self, store, events, sector: str = "financials",
                 horizon_days: dict | None = None) -> None:
        self.store = store
        self.events = events
        self.sector = get_sector(sector)
        # Trading days per horizon; Settings can change this (UI-04).
        self.horizon_days = dict(horizon_days or DEFAULT_HORIZON_DAYS)

    # ---- public API ----------------------------------------------------------------------
    def simulate_joint_returns(
        self,
        as_of: datetime,
        security_ids: list[str],
        horizon_days: int,
        assumptions: ScenarioAssumptions,
        n_paths: int = 2000,
        seed: int = 0,
    ) -> np.ndarray:
        as_of = ensure_utc(as_of)
        self._check_ids(security_ids)
        if horizon_days <= 0 or n_paths <= 0:
            raise ValueError("horizon_days and n_paths must be positive.")
        risky = [s for s in dict.fromkeys(security_ids) if s != CASH_ID]
        out = np.zeros((n_paths, horizon_days, len(security_ids)))
        if not risky:
            return out
        hist = self._history(as_of, risky, assumptions.lookback_years)
        if len(hist.rets) < MIN_SIM_DAYS:
            raise ValueError(
                f"Only {len(hist.rets)} joint days of history for {risky} as of "
                f"{as_of.isoformat()}; need at least {MIN_SIM_DAYS}."
            )
        _, feats = build_feature_snapshot(self.store, as_of, risky)
        drifts = {
            s: sum(self._drift_parts(as_of, s, horizon_days, assumptions, hist, feats)[0].values())
            / horizon_days
            for s in risky
        }
        cols = list(hist.rets.columns)
        sim_seed = self._seed(as_of, cols, n_paths, horizon_days, assumptions, seed)
        idx = stationary_bootstrap_indices(len(hist.rets), n_paths, horizon_days, sim_seed)
        sample = hist.rets.to_numpy()[idx]  # (paths, days, cols)
        vm = assumptions.volatility_multiplier
        for j, sid in enumerate(security_ids):
            if sid == CASH_ID:
                continue
            c = cols.index(sid)
            out[:, :, j] = drifts[sid] + vm * (sample[:, :, c] - hist.mu[sid])
        return out

    def forecast(
        self,
        as_of: datetime,
        security_ids: list[str],
        horizons: list[Horizon],
        assumptions: ScenarioAssumptions,
    ) -> ForecastRun:
        as_of = ensure_utc(as_of)
        self._check_ids(security_ids)
        horizons = list(dict.fromkeys(horizons))
        risky = [s for s in dict.fromkeys(security_ids) if s != CASH_ID]
        prices = self.store.prices(list(dict.fromkeys(risky + [MARKET_ID])), as_of)
        data_cutoff = (prices["available_at"].max().to_pydatetime() if len(prices) else as_of)
        snapshot_id, feats = build_feature_snapshot(self.store, as_of, risky) if risky \
            else (None, pd.DataFrame())

        hist = self._history(as_of, risky, assumptions.lookback_years) if risky else None
        counts = hist.counts if hist else {}
        eligible = [s for s in risky if counts.get(s, 0) >= MIN_FORECAST_DAYS]
        sims: dict[str, np.ndarray] = {}
        if eligible:
            joint = self._history(as_of, eligible, assumptions.lookback_years)
            max_h = max(self.horizon_days[h] for h in horizons) if horizons else 0
            cols = list(joint.rets.columns)
            sim_seed = self._seed(as_of, cols, FORECAST_PATHS, max_h, assumptions, 0)
            idx = stationary_bootstrap_indices(len(joint.rets), FORECAST_PATHS, max_h, sim_seed)
            arr = joint.rets.to_numpy()
            for s in eligible:
                c = cols.index(s)
                sims[s] = arr[:, c][idx] - joint.mu[s]  # demeaned paths (paths, days)
            hist = joint

        forecasts: list[SecurityForecast] = []
        for sid in security_ids:
            for h in horizons:
                forecasts.append(
                    self._one(as_of, sid, h, assumptions, prices, feats, snapshot_id, hist,
                              counts, sims)
                )

        request = {
            "as_of": as_of,
            "security_ids": list(security_ids),
            "horizons": [h.value for h in horizons],
            "assumptions": assumptions,
        }
        return ForecastRun(
            run_id=uuid.uuid4().hex,
            as_of=as_of,
            data_cutoff=data_cutoff,
            security_ids=list(security_ids),
            horizons=horizons,
            assumptions=assumptions,
            forecasts=forecasts,
            model_version=MODEL_VERSION,
            input_hash=stable_hash({"request": request, "data_cutoff": data_cutoff,
                                    "horizon_days": self.horizon_days}),
            created_at=datetime.now(timezone.utc),
        )

    # ---- one security x horizon -------------------------------------------------------------
    def _one(self, as_of, sid, h, assumptions, prices, feats, snapshot_id, hist, counts, sims):
        days = self.horizon_days[h]
        px = prices[prices["security_id"] == sid]
        start_price = float(px["raw_close"].iloc[-1]) if len(px) else None
        start_date = px["trading_date"].iloc[-1].date().isoformat() if len(px) else None
        base = {
            "security_id": sid,
            "horizon": h,
            "horizon_trading_days": days,
            "start_price": start_price,
            "start_date": start_date,
            "method": METHOD,
            "model_version": MODEL_VERSION,
            "feature_snapshot_id": snapshot_id,
        }
        if sid == CASH_ID:
            return SecurityForecast(
                **base, status=Confidence.UNAVAILABLE,
                status_reason="CASH is not forecast here; the portfolio layer applies the "
                              "configured cash yield with zero volatility.")
        n = counts.get(sid, 0)
        if sid not in sims or start_price is None:
            return SecurityForecast(
                **base, status=Confidence.UNAVAILABLE, sample_size=n,
                status_reason=f"Only {n} trading days of history in the lookback window; "
                              f"need at least {MIN_FORECAST_DAYS}.")
        if n < MEDIUM_FORECAST_DAYS:
            status, reason = Confidence.LOW, (
                f"{n} days of history (< {MEDIUM_FORECAST_DAYS}); uncalibrated model.")
        elif days > n / 3:
            status, reason = Confidence.LOW, (
                f"Horizon {days} days is longer than a third of the {n}-day history.")
        else:
            status, reason = Confidence.MEDIUM, "Uncalibrated model: MEDIUM at most in the MVP."

        parts, words = self._drift_parts(as_of, sid, days, assumptions, hist, feats)
        drift_total = sum(parts.values())
        x = drift_total / days + assumptions.volatility_multiplier * sims[sid][:, :days]
        horizon_ret = np.expm1(np.log1p(np.clip(x, -0.999, None)).sum(axis=1))
        q = {name: float(np.quantile(horizon_ret, p)) for name, p in QUANTILES.items()}
        lo, hi = (float(np.quantile(horizon_ret, p)) for p in INTERVAL)
        drivers = {k: round(v, 10) for k, v in parts.items()}
        drivers["distribution_median_adjustment"] = round(q[ScenarioName.BASE] - drift_total, 10)

        scenarios = []
        for name, p in QUANTILES.items():
            ret = q[name]
            scenarios.append(ScenarioForecast(
                scenario=name, quantile=p, projected_return=ret,
                projected_price=start_price * (1 + ret),
                interval_low=start_price * (1 + lo), interval_high=start_price * (1 + hi),
                interval_coverage=INTERVAL[1] - INTERVAL[0],
                assumptions_applied=words + [
                    (f"{name.value.capitalize()} = {int(p * 100)}th percentile of "
                     f"{FORECAST_PATHS} simulated {days}-day price returns (block bootstrap, "
                     f"mean block {MEAN_BLOCK_LENGTH:g} days)."),
                    NOTE,
                ],
            ))
        return SecurityForecast(**base, scenarios=scenarios, status=status, status_reason=reason,
                                sample_size=n, drivers=drivers)

    # ---- drift ----------------------------------------------------------------------------
    def _drift_parts(self, as_of, sid, days, a: ScenarioAssumptions, hist: _History, feats):
        """Named horizon-total contributions to the base drift, plus plain-word descriptions."""
        words: list[str] = []
        mu = float(hist.mu[sid])
        beta = float(hist.beta.get(sid, math.nan))
        if math.isfinite(beta) and math.isfinite(hist.mu_market):
            hist_daily = (1 - HIST_SHRINK) * mu + HIST_SHRINK * beta * hist.mu_market
            words.append(f"History: mean daily return shrunk 50% toward beta ({beta:.2f}) x "
                         f"market mean, over {a.lookback_years:g} years.")
        else:
            hist_daily = mu
            words.append("History: mean daily return (no market beta available).")
        history = hist_daily * days

        f = feats.loc[sid] if sid in feats.index else None
        gap = float(f["analyst_target_gap"]) if f is not None else math.nan
        if math.isfinite(gap):
            w = a.analyst_weight
            analyst = gap * min(days, ANALYST_HORIZON_DAYS) / ANALYST_HORIZON_DAYS
            words.append(f"Analyst targets: mean target implies {gap:+.1%} over 12 months "
                         f"({int(f['analyst_count'])} firm(s), last 365 days), weight {w:.0%}, "
                         f"prorated to {days} days. Opinion, not observed fact.")
        else:
            w, analyst = 0.0, 0.0
            words.append("Analyst targets: none available as of this time; history only.")

        rate = 0.0
        if a.rate_change_bps:
            rs = float(f["rate_sensitivity"]) if f is not None else math.nan
            rt = float(f["rate_sensitivity_t"]) if f is not None else math.nan
            if math.isfinite(rs) and math.isfinite(rt) and abs(rt) >= RATE_T_MIN:
                rate = a.rate_change_bps / 100 * rs
                words.append(f"Rate change {a.rate_change_bps:+g} bps x estimated sensitivity "
                             f"{rs:+.3f} per 100 bps of 2-year yield (t={rt:.1f}).")
            else:
                rate = a.rate_change_bps / 25 * SECTOR_RATE_DEFAULT_PER_25BPS
                words.append(f"Rate change {a.rate_change_bps:+g} bps x sector default "
                             f"+0.4% per +25 bps (own estimate missing or |t| < 1).")

        earn = 0.0
        if a.earnings_surprise_pct:
            coef, n = self._earnings_coefficient(as_of, sid)
            earn = a.earnings_surprise_pct * coef
            if n >= EARNINGS_MIN_SAMPLES:
                words.append(f"Earnings surprise {a.earnings_surprise_pct:+g}% x {coef:+.4f} "
                             f"CAR per 1% surprise ({n} past results).")
            else:
                words.append(f"Earnings surprise {a.earnings_surprise_pct:+g}%: only {n} past "
                             f"results measured (< {EARNINGS_MIN_SAMPLES}), so no effect applied.")

        market = 0.0
        if a.market_return_shift_pct:
            b = beta if math.isfinite(beta) else 1.0
            market = a.market_return_shift_pct / 100 * b * days / TRADING_DAYS_YEAR
            words.append(f"Market shift {a.market_return_shift_pct:+g}% a year x beta {b:.2f}, "
                         f"prorated to {days} days.")
        if a.volatility_multiplier != 1.0:
            words.append(f"Volatility scaled x{a.volatility_multiplier:g}.")

        parts = {
            "history": (1 - w) * history,
            "analyst_targets": w * analyst,
            "rate_change": rate,
            "earnings_surprise": earn,
            "market_shift": market,
        }
        return parts, words

    def _earnings_coefficient(self, as_of, sid) -> tuple[float, int]:
        """OLS through the origin of realized CAR on surprise (percent): the mean CAR per 1%
        surprise. 0 when fewer than 6 measured results."""
        evs = [e for e in self.events.list_events(as_of, [sid], [EventClass.SCHEDULED])
               if e.subtype == "quarterly_results" and e.surprise is not None
               and sid in e.affected_security_ids]
        if not evs:
            return 0.0, 0
        est = {i.event_id: i for i in self.events.impact_estimates(as_of, security_id=sid)
               if i.realized and i.abnormal_return is not None}
        pairs = [(e.surprise * 100, est[e.event_id].abnormal_return)
                 for e in evs if e.event_id in est]
        n = len(pairs)
        if n < EARNINGS_MIN_SAMPLES:
            return 0.0, n
        s = np.array([p[0] for p in pairs])
        c = np.array([p[1] for p in pairs])
        ss = float((s**2).sum())
        return (float((s * c).sum() / ss) if ss > 0 else 0.0), n

    # ---- data -------------------------------------------------------------------------------
    def _check_ids(self, security_ids: list[str]) -> None:
        if not security_ids:
            raise ValueError("security_ids is empty.")
        known = {s.security_id for s in self.store.securities()}
        known |= {s.security_id for s in self.sector.universe()}
        known |= {s.security_id for s in self.sector.benchmarks()} | {CASH_ID}
        unknown = [s for s in security_ids if s not in known]
        if unknown:
            raise ValueError(f"Unknown security id(s): {unknown}")

    def _history(self, as_of, risky: list[str], lookback_years: float) -> _History:
        ids = list(dict.fromkeys(risky + [MARKET_ID]))
        rets = price_returns(self.store, ids, as_of)  # price return: splits only, no dividends
        rets = rets.reindex(columns=ids)
        if len(rets):
            start = rets.index.max() - timedelta(days=lookback_years * 365.25)
            rets = rets[rets.index > start]
        counts = {s: int(rets[s].notna().sum()) for s in risky}
        have_mkt = rets[MARKET_ID].notna().sum() >= MIN_SIM_DAYS
        cols = risky + ([MARKET_ID] if have_mkt and MARKET_ID not in risky else [])
        joint = rets[cols].dropna()
        mu = joint.mean()
        beta = pd.Series(math.nan, index=cols)
        mu_m = math.nan
        if have_mkt and len(joint) >= MIN_SIM_DAYS:
            m = joint[MARKET_ID].to_numpy()
            vm = float(np.var(m, ddof=1))
            mu_m = float(m.mean())
            for c in cols:
                beta[c] = float(np.cov(m, joint[c].to_numpy(), ddof=1)[0, 1] / vm) if vm > 0 \
                    else math.nan
        return _History(rets=joint, mu=mu, beta=beta, mu_market=mu_m, counts=counts)

    def _seed(self, as_of, cols, n_paths, days, a: ScenarioAssumptions, seed: int) -> int:
        """RNG seed from the inputs that shape the bootstrap draw (not the drift assumptions,
        so changing an assumption moves every path the same way: common random numbers)."""
        return seed_from_hash(stable_hash({
            "as_of": as_of, "columns": cols, "n_paths": n_paths, "days": days,
            "lookback_years": a.lookback_years, "seed": seed,
        }))

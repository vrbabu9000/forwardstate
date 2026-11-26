"""Simple test doubles for the portfolio, risk and alert tests (not the real forecaster).

- ``BootstrapForecaster``: block-bootstraps whole rows (days) of ``store.returns()`` so the
  cross-asset correlation is kept. CASH gets zeros (the risk layer applies the cash yield).
- ``SimpleEventService``: stored events plus a realized abnormal return per affected security
  (event-day return minus SPY's return that day), using only data available by ``as_of``.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd

from forwardstate.contracts import (
    CASH_ID,
    Confidence,
    Direction,
    Event,
    EventClass,
    EventStatus,
    ForecastRun,
    Horizon,
    ImpactEstimate,
    ScenarioAssumptions,
)


class BootstrapForecaster:
    def __init__(self, store, block: int = 5, min_history: int = 60) -> None:
        self.store = store
        self.block = block
        self.min_history = min_history
        self.calls: list[datetime] = []

    def forecast(self, as_of, security_ids, horizons: list[Horizon],
                 assumptions: ScenarioAssumptions) -> ForecastRun:  # pragma: no cover
        raise NotImplementedError("Not needed by the risk tests.")

    def simulate_joint_returns(self, as_of: datetime, security_ids: list[str], horizon_days: int,
                               assumptions: ScenarioAssumptions, n_paths: int = 2000,
                               seed: int = 0) -> np.ndarray:
        self.calls.append(as_of)
        risky = [s for s in security_ids if s != CASH_ID]
        start = (as_of - timedelta(days=int(365 * assumptions.lookback_years))).date()
        hist = self.store.returns(risky, as_of, start=start).dropna()
        if len(hist) < self.min_history or list(hist.columns) != risky:
            raise ValueError(f"only {len(hist)} days of history")
        x = hist.to_numpy()
        mean = x.mean(axis=0)
        x = mean + (x - mean) * assumptions.volatility_multiplier
        rng = np.random.default_rng(seed)
        n_blocks = -(-horizon_days // self.block)
        starts = rng.integers(0, len(x) - self.block + 1, size=(n_paths, n_blocks))
        idx = (starts[:, :, None] + np.arange(self.block)).reshape(n_paths, -1)[:, :horizon_days]
        sim = x[idx]  # (paths, days, risky)
        out = np.zeros((n_paths, horizon_days, len(security_ids)))
        for j, s in enumerate(security_ids):
            if s != CASH_ID:
                out[:, :, j] = sim[:, :, risky.index(s)]
        return out


class SimpleEventService:
    def __init__(self, store, benchmark: str = "SPY") -> None:
        self.store = store
        self.benchmark = benchmark

    def list_events(self, as_of: datetime, security_ids: list[str] | None = None,
                    event_classes: list[EventClass] | None = None, start: date | None = None,
                    end: date | None = None) -> list[Event]:
        return self.store.events(as_of, security_ids, event_classes, start, end)

    def impact_estimates(self, as_of: datetime, event_id: str | None = None,
                         security_id: str | None = None) -> list[ImpactEstimate]:
        out = []
        for e in self.store.events(as_of):
            if event_id and e.event_id != event_id:
                continue
            if e.status != EventStatus.OCCURRED or e.occurred_at is None:
                continue
            ids = [s for s in e.affected_security_ids if not security_id or s == security_id]
            if not ids:
                continue
            day = e.occurred_at.date()
            r = self.store.returns([*ids, self.benchmark], as_of, start=day - timedelta(days=7),
                                   end=day)
            if r.empty or pd.Timestamp(day) not in r.index:
                continue
            row = r.loc[pd.Timestamp(day)]
            for s in ids:
                ar = float(row[s] - row[self.benchmark])
                out.append(ImpactEstimate(
                    event_id=e.event_id, security_id=s, realized=True, window_pre_days=0,
                    window_post_days=0,
                    direction=Direction.DOWN if ar < 0 else Direction.UP,
                    abnormal_return=ar, event_day_return=float(row[s]),
                    benchmark_id=self.benchmark, method="test-fake: event-day return minus SPY",
                    sample_size=1, confidence=Confidence.LOW, as_of=as_of,
                ))
        return out

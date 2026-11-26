"""ForecastEngine: AC-02, AC-03, determinism, point-in-time and data sufficiency."""

from __future__ import annotations

import time
from datetime import date

import numpy as np
import pytest

from forwardstate.contracts import (
    Confidence,
    Horizon,
    ScenarioAssumptions,
    ScenarioName,
)
from forwardstate.events import EventEngine
from forwardstate.forecasting import METHOD, ForecastEngine
from forwardstate.pit import as_of_for_date
from forwardstate.services import ForecastService
from forwardstate.testing import FixtureStore, build_synthetic_dataset, synthetic_as_of
from forwardstate.testing.synthetic import SyntheticDataset

BANKS = ["JPM", "BAC", "C", "MS", "GS"]


def _engine(store=None) -> ForecastEngine:
    store = store or FixtureStore()
    return ForecastEngine(store, EventEngine(store))


def _truncated_store(as_of) -> FixtureStore:
    ds = build_synthetic_dataset()
    keep = [b for b in ds.bars if b.available_at <= as_of]
    return FixtureStore(SyntheticDataset(
        securities=ds.securities,
        bars=keep,
        actions=[a for a in ds.actions if a.available_at <= as_of],
        observations=[o for o in ds.observations if o.available_at <= as_of],
        events=[e for e in ds.events if e.available_at <= as_of],
        analyst=[o for o in ds.analyst if o.available_at <= as_of],
        trading_days=[d for d in ds.trading_days if d <= as_of.date()],
    ))


def _base(run, sid, h):
    f = next(f for f in run.forecasts if f.security_id == sid and f.horizon == h)
    return next(s for s in f.scenarios if s.scenario == ScenarioName.BASE).projected_return


def test_protocol():
    assert isinstance(_engine(), ForecastService)


def test_ac03_three_scenarios_three_horizons_ordered():
    run = _engine().forecast(synthetic_as_of(), ["JPM"], list(Horizon), ScenarioAssumptions())
    assert len(run.forecasts) == 3
    for f in run.forecasts:
        assert f.method == METHOD and f.status in (Confidence.MEDIUM, Confidence.LOW)
        s = {x.scenario: x for x in f.scenarios}
        assert set(s) == set(ScenarioName)
        o, b, p = s[ScenarioName.OPTIMISTIC], s[ScenarioName.BASE], s[ScenarioName.PESSIMISTIC]
        assert o.projected_return >= b.projected_return >= p.projected_return
        assert b.interval_low <= b.projected_price <= b.interval_high
        assert all(x.interval_coverage == pytest.approx(0.8) and x.probability is None
                   for x in f.scenarios)
        assert f.drivers and b.assumptions_applied


def test_ac02_assumptions_move_base_in_expected_direction():
    eng, t = _engine(), synthetic_as_of()
    h = [Horizon.SHORT, Horizon.MEDIUM]
    neutral = eng.forecast(t, ["JPM"], h, ScenarioAssumptions())
    up_rate = eng.forecast(t, ["JPM"], h, ScenarioAssumptions(rate_change_bps=50))
    down_rate = eng.forecast(t, ["JPM"], h, ScenarioAssumptions(rate_change_bps=-50))
    for hz in h:
        assert _base(up_rate, "JPM", hz) > _base(neutral, "JPM", hz) > _base(down_rate, "JPM", hz)
    earn = eng.forecast(t, ["JPM"], h, ScenarioAssumptions(earnings_surprise_pct=10))
    f = next(f for f in earn.forecasts if f.horizon == Horizon.SHORT)
    coef_sign = np.sign(f.drivers["earnings_surprise"])
    assert coef_sign != 0
    assert np.sign(_base(earn, "JPM", Horizon.SHORT) - _base(neutral, "JPM", Horizon.SHORT)) \
        == coef_sign


def test_determinism():
    eng, t = _engine(), synthetic_as_of()
    a = eng.forecast(t, BANKS, list(Horizon), ScenarioAssumptions()).model_dump()
    b = _engine().forecast(t, BANKS, list(Horizon), ScenarioAssumptions()).model_dump()
    for d in (a, b):
        d.pop("run_id"), d.pop("created_at")
    assert a == b


def test_pit_forecast_unchanged_when_future_data_removed():
    t = as_of_for_date(date(2023, 3, 10))
    full = _engine().forecast(t, BANKS, list(Horizon), ScenarioAssumptions()).model_dump()
    cut = _engine(_truncated_store(t)).forecast(t, BANKS, list(Horizon),
                                                ScenarioAssumptions()).model_dump()
    for d in (full, cut):
        d.pop("run_id"), d.pop("created_at")
    assert full == cut
    assert all(f["status"] == Confidence.LOW for f in full["forecasts"])  # ~300 days


def test_unavailable_with_too_little_history():
    t = as_of_for_date(date(2022, 6, 30))
    run = _engine().forecast(t, ["JPM", "CASH"], [Horizon.SHORT], ScenarioAssumptions())
    for f in run.forecasts:
        assert f.status == Confidence.UNAVAILABLE and f.scenarios == [] and f.status_reason


def test_simulate_joint_shape_cash_and_correlation():
    eng = _engine()
    x = eng.simulate_joint_returns(synthetic_as_of(), ["JPM", "CASH", "BAC"], 20,
                                   ScenarioAssumptions(), n_paths=500, seed=3)
    assert x.shape == (500, 20, 3)
    assert np.all(x[:, :, 1] == 0)
    assert np.corrcoef(x[:, :, 0].ravel(), x[:, :, 2].ravel())[0, 1] > 0.5
    y = eng.simulate_joint_returns(synthetic_as_of(), ["JPM", "CASH", "BAC"], 20,
                                   ScenarioAssumptions(), n_paths=500, seed=3)
    assert np.array_equal(x, y)
    hi = eng.simulate_joint_returns(synthetic_as_of(), ["JPM", "CASH", "BAC"], 20,
                                    ScenarioAssumptions(volatility_multiplier=2.0), n_paths=500,
                                    seed=3)
    assert hi[:, :, 0].std() == pytest.approx(2 * x[:, :, 0].std(), rel=1e-6)


def test_simulate_errors():
    eng = _engine()
    with pytest.raises(ValueError, match="Unknown"):
        eng.simulate_joint_returns(synthetic_as_of(), ["NOPE"], 5, ScenarioAssumptions())
    with pytest.raises(ValueError, match="at least 60"):
        eng.simulate_joint_returns(as_of_for_date(date(2022, 2, 15)), ["JPM"], 5,
                                   ScenarioAssumptions())


def test_performance_five_securities_three_horizons():
    eng = _engine()
    t0 = time.perf_counter()
    eng.forecast(synthetic_as_of(), BANKS, list(Horizon), ScenarioAssumptions(rate_change_bps=25))
    assert time.perf_counter() - t0 < 3.0

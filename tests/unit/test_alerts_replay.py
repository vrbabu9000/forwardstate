"""AC-05: replaying the synthetic March 2023 sector shock triggers an explainable alert.

Rules come from configs/risk.example.yaml unchanged; no threshold was tuned for this test.
"""

import time
from datetime import date
from pathlib import Path

import pytest
import yaml
from fakes_risk import BootstrapForecaster, SimpleEventService

from forwardstate.alerts import AlertEngine, load_rules
from forwardstate.contracts import Portfolio, ScenarioAssumptions
from forwardstate.portfolio import PortfolioEngine
from forwardstate.testing import FixtureStore

ROOT = Path(__file__).resolve().parents[2]
A = ScenarioAssumptions()


@pytest.fixture(scope="module")
def store():
    return FixtureStore()


@pytest.fixture()
def demo():
    return Portfolio(**yaml.safe_load((ROOT / "configs/portfolio.example.yaml").read_text()))


def make(store):
    f = BootstrapForecaster(store)
    return AlertEngine(store, f, SimpleEventService(store), PortfolioEngine(store, f), load_rules())


def test_ac05_replay_march_2023(store, demo):
    eng = make(store)
    res = eng.replay(demo, date(2023, 3, 1), date(2023, 3, 31), A)
    assert len(res.frames) == 23 and res.frames[0].portfolio_value == pytest.approx(100_000)
    by_day = {f.as_of: f for f in res.frames}
    assert by_day[date(2023, 3, 13)].portfolio_value < 0.95 * by_day[date(2023, 3, 10)].portfolio_value
    assert all(f.metrics is not None for f in res.frames)
    assert res.alerts, "the shock must trigger at least one alert"
    shock = [a for a in res.alerts if "stress-2023-03-13" in [e.ref_id for e in a.evidence]]
    assert shock, "an alert must cite the 2023-03-13 stress as evidence"
    a = next(x for x in shock if x.rule_id == "event_shock")
    assert a.projected_loss and a.projected_loss > 0  # loss scenario
    labels = [o.label for o in a.alternatives]
    assert labels[0] == "Hold (no change)" and "Move 50% to cash" in labels  # hold vs defensive
    assert a.alternatives[2].cvar_95 < a.alternatives[0].cvar_95
    new_ids = {i for f in res.frames for i in f.new_alert_ids}
    assert new_ids == {x.alert_id for x in res.alerts}
    # Alerts before the shock date never cite it (point-in-time).
    for x in res.alerts:
        if x.as_of < shock[0].as_of:
            assert "stress-2023-03-13" not in [e.ref_id for e in x.evidence]
    assert {x.alert_id for x in eng.list_alerts()} == new_ids  # replay alerts are listed


def test_replay_is_deterministic(store, demo):
    a = make(store).replay(demo, date(2023, 3, 6), date(2023, 3, 17), A)
    b = make(store).replay(demo, date(2023, 3, 6), date(2023, 3, 17), A)
    assert a.model_dump() == b.model_dump()


def test_replay_60_days_under_15_seconds(store, demo):
    t = time.perf_counter()
    res = make(store).replay(demo, date(2023, 1, 3), date(2023, 3, 27), A)
    took = time.perf_counter() - t
    assert len(res.frames) == 60
    assert took < 15, f"replay took {took:.1f}s"

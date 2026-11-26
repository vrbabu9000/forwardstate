"""Alert content, lifecycle, cooldown, persistence, point-in-time and data failures."""

from datetime import date
from pathlib import Path

import pytest
import yaml
from fakes_risk import BootstrapForecaster, SimpleEventService

from forwardstate.alerts import AlertEngine, load_rules
from forwardstate.contracts import (
    DECISION_BOUNDARY,
    AlertStatus,
    Confidence,
    Portfolio,
    ScenarioAssumptions,
    stable_hash,
)
from forwardstate.pit import as_of_for_date
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


def make(store, forecaster=None, **kw):
    f = forecaster or BootstrapForecaster(store)
    return AlertEngine(store, f, SimpleEventService(store), PortfolioEngine(store, f),
                       load_rules(), n_paths=500, **kw)


def day(d):
    return as_of_for_date(d)


def test_load_rules():
    rules = load_rules()
    assert [r.rule_id for r in rules] == [
        "forecast_loss_short", "downside_prob_short", "realized_loss_5d", "concentration",
        "event_shock"]
    assert rules[1].loss_level == 0.05 and rules[2].lookback_trading_days == 5


def test_alert_content_after_the_shock(store, demo):
    eng = make(store)
    as_of = day(date(2023, 3, 13))
    alerts = {a.rule_id: a for a in eng.evaluate_alerts(demo, as_of, A)}
    assert {"realized_loss_5d", "event_shock", "forecast_loss_short"} <= set(alerts)
    a = alerts["forecast_loss_short"]
    rule = next(r for r in eng.rules() if r.rule_id == a.rule_id)
    assert a.alert_id == stable_hash([rule, as_of, demo, A, eng.n_paths])[:16]
    assert a.title and a.summary and a.severity.value == "high"
    assert a.metric_value > a.threshold == 0.05
    assert a.projected_loss > 0 and a.projected_loss == pytest.approx(a.projected_loss_pct * 100_000)
    assert 0 <= a.probability <= 1
    assert a.confidence == Confidence.LOW
    assert any("simulated, not calibrated" in s.lower() for s in a.limitations)
    assert any("cash is assumed to earn" in s.lower() for s in a.limitations)
    assert a.current_exposure["JPM"] == 0.3
    kinds = {e.kind for e in a.evidence}
    assert {"event", "price", "model"} <= kinds
    assert all(e.origin.value in {"synthetic", "derived"} for e in a.evidence)
    assert "stress-2023-03-13" in [e.ref_id for e in a.evidence]
    labels = [o.label for o in a.alternatives]
    assert labels == ["Hold (no change)", "Move 25% to cash", "Move 50% to cash"]
    hold, _, half = a.alternatives
    assert half.cvar_95 < hold.cvar_95 and half.projected_loss < hold.projected_loss
    assert hold.est_cost == 0 and half.est_cost > 0 and half.missed_upside >= 0
    assert all("not an instruction" in o.note for o in a.alternatives)
    assert a.expires_at == day(date(2023, 3, 20))  # 5 trading days later
    assert a.decision_boundary == DECISION_BOUNDARY
    ev = alerts["event_shock"]
    assert ev.triggering_event_ids == ["stress-2023-03-13"]
    rl = alerts["realized_loss_5d"]
    assert "realized" in rl.summary and rl.metric_value > 0.04


def test_point_in_time_alert_before_the_shock_does_not_see_it(store, demo):
    f = BootstrapForecaster(store)
    eng = make(store, f)
    as_of = day(date(2023, 3, 10))
    alerts = eng.evaluate_alerts(demo, as_of, A)
    assert all(c <= as_of for c in f.calls)
    assert "event_shock" not in {a.rule_id for a in alerts}
    assert "realized_loss_5d" not in {a.rule_id for a in alerts}
    for a in alerts:
        refs = [e.ref_id for e in a.evidence]
        assert "stress-2023-03-13" not in refs
        assert all(e.at is None or e.at <= as_of for e in a.evidence)
        price = next(e for e in a.evidence if e.kind == "price")
        assert price.ref_id.endswith("2023-03-10")


def test_lifecycle_transitions(store, demo):
    eng = make(store)
    a = eng.evaluate_alerts(demo, day(date(2023, 3, 13)), A, rule_ids=["realized_loss_5d"])[0]
    assert a.status == AlertStatus.NEW
    assert eng.transition(a.alert_id, AlertStatus.ACKNOWLEDGED, "seen").status == \
        AlertStatus.ACKNOWLEDGED
    assert eng.transition(a.alert_id, AlertStatus.RESOLVED).status == AlertStatus.RESOLVED
    with pytest.raises(ValueError):
        eng.transition(a.alert_id, AlertStatus.ACKNOWLEDGED)
    with pytest.raises(ValueError):
        eng.transition(a.alert_id, AlertStatus.NEW)
    b = eng.evaluate_alerts(demo, day(date(2023, 3, 13)), A, rule_ids=["event_shock"])[0]
    with pytest.raises(ValueError):
        eng.transition(b.alert_id, AlertStatus.SUPERSEDED)  # engine-only status
    with pytest.raises(KeyError):
        eng.transition("nope", AlertStatus.RESOLVED)
    assert [t.to_status for t in eng.transitions(a.alert_id)] == [
        AlertStatus.ACKNOWLEDGED, AlertStatus.RESOLVED]
    assert eng.list_alerts(AlertStatus.RESOLVED)[0].alert_id == a.alert_id


def test_cooldown_then_supersede(store, demo):
    eng = make(store)
    rid = ["forecast_loss_short"]
    first = eng.evaluate_alerts(demo, day(date(2023, 3, 1)), A, rid)
    assert len(first) == 1
    assert eng.evaluate_alerts(demo, day(date(2023, 3, 2)), A, rid) == []  # cooldown
    assert eng.evaluate_alerts(demo, day(date(2023, 3, 7)), A, rid) == []  # 4 trading days
    second = eng.evaluate_alerts(demo, day(date(2023, 3, 8)), A, rid)  # 5 trading days
    assert len(second) == 1
    old = next(a for a in eng.list_alerts() if a.alert_id == first[0].alert_id)
    assert old.status == AlertStatus.SUPERSEDED and old.superseded_by == second[0].alert_id
    assert second[0].status == AlertStatus.NEW
    # Same inputs again: same alert, no duplicate.
    again = eng.evaluate_alerts(demo, day(date(2023, 3, 8)), A, rid)
    assert [a.alert_id for a in again] == [second[0].alert_id] and len(eng.list_alerts()) == 2


def test_persistence(store, demo, tmp_path):
    path = tmp_path / "alerts.json"
    eng = make(store, persist_path=path)
    a = eng.evaluate_alerts(demo, day(date(2023, 3, 13)), A, ["realized_loss_5d"])[0]
    eng.transition(a.alert_id, AlertStatus.ACKNOWLEDGED)
    again = make(store, persist_path=path)
    assert [x.status for x in again.list_alerts()] == [AlertStatus.ACKNOWLEDGED]
    assert len(again.transitions()) == 1
    # Cooldown survives a restart.
    assert again.evaluate_alerts(demo, day(date(2023, 3, 14)), A, ["realized_loss_5d"]) == []


def test_missing_data_gives_no_false_alert(store, demo):
    class Broken(BootstrapForecaster):
        def simulate_joint_returns(self, *a, **k):
            raise ValueError("price history missing")

    eng = make(store, Broken(store))
    alerts = eng.evaluate_alerts(demo, day(date(2023, 3, 13)), A)
    rules = {a.rule_id for a in alerts}
    assert not rules & {"forecast_loss_short", "downside_prob_short"}
    assert any("could not be simulated" in s for s in eng.last_limitations)
    rl = next(a for a in alerts if a.rule_id == "realized_loss_5d")  # measured, still valid
    assert rl.projected_loss is None and rl.probability is None
    assert rl.confidence == Confidence.UNAVAILABLE
    assert any("could not be simulated" in s for s in rl.limitations)


def test_before_any_data_nothing_fires(store, demo):
    eng = make(store)
    assert eng.evaluate_alerts(demo, day(date(2021, 6, 1)), A) == []
    assert any("No price data" in s for s in eng.last_limitations)


def test_deterministic(store, demo):
    as_of = day(date(2023, 3, 14))
    a = [x.model_dump() for x in make(store).evaluate_alerts(demo, as_of, A)]
    b = [x.model_dump() for x in make(store).evaluate_alerts(demo, as_of, A)]
    assert a == b and a


def test_no_trading_code():
    src = ROOT / "src/forwardstate"
    text = "".join(p.read_text().lower() for d in ("alerts", "portfolio", "risk")
                   for p in (src / d).glob("*.py"))
    for word in ("place_order", "submit_order", "execute_trade", "broker", "requests.post"):
        assert word not in text

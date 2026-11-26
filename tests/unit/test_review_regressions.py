"""Regression tests for the independent backend review (Wave 2). Each test pins one finding."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
import yaml

from forwardstate.alerts import AlertEngine, load_rules
from forwardstate.contracts import AlertMetric, Portfolio, ScenarioAssumptions
from forwardstate.events import EventEngine
from forwardstate.forecasting import ForecastEngine
from forwardstate.forecasting.engine import price_returns
from forwardstate.pit import as_of_for_date
from forwardstate.portfolio import PortfolioEngine
from forwardstate.testing import FixtureStore

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def store():
    return FixtureStore()


@pytest.fixture(scope="module")
def demo():
    return Portfolio.model_validate(yaml.safe_load((ROOT / "configs/portfolio.example.yaml").read_text()))


def engine(store, rules=None):
    ev = EventEngine(store)
    fc = ForecastEngine(store, ev)
    pe = PortfolioEngine(store, fc, n_paths=500)
    return AlertEngine(store, fc, ev, pe, rules or load_rules(ROOT / "configs/risk.example.yaml"),
                       n_paths=500)


def ids(alerts):
    return sorted((a.rule_id, a.alert_id) for a in alerts)


def test_finding1_later_alerts_do_not_suppress_earlier_as_of(store, demo):
    a = ScenarioAssumptions()
    fresh = engine(store).evaluate_alerts(demo, as_of_for_date(date(2023, 3, 13)), a)
    eng = engine(store)
    eng.evaluate_alerts(demo, as_of_for_date(date(2023, 3, 17)), a)
    after = eng.evaluate_alerts(demo, as_of_for_date(date(2023, 3, 13)), a)
    assert ids(after) == ids(fresh)


def test_finding2_assumptions_change_the_alert(store, demo):
    eng = engine(store)
    as_of = as_of_for_date(date(2023, 3, 13))
    base = {x.rule_id: x for x in eng.evaluate_alerts(demo, as_of, ScenarioAssumptions())}
    wild = {x.rule_id: x for x in eng.evaluate_alerts(demo, as_of, ScenarioAssumptions(volatility_multiplier=3))}
    rid = "forecast_loss_short"
    assert rid in base and rid in wild
    assert wild[rid].alert_id != base[rid].alert_id
    assert wild[rid].projected_loss > base[rid].projected_loss


def test_finding3_event_shock_rule_can_fire_within_its_window(store, demo):
    rules = [r for r in load_rules(ROOT / "configs/risk.example.yaml") if r.metric == AlertMetric.EVENT_SEVERITY]
    fired = engine(store, rules).evaluate_alerts(demo, as_of_for_date(date(2023, 3, 15)), ScenarioAssumptions())
    assert fired, "event_shock must be able to fire within its 5-day window"
    assert any("2023-03-13" in e for a in fired for e in a.triggering_event_ids)


def test_finding4_forecast_uses_price_not_total_returns(store):
    as_of = as_of_for_date(date(2024, 12, 31))
    price = price_returns(store, ["JPM"], as_of)["JPM"]
    total = store.returns(["JPM"], as_of)["JPM"]
    # the fixture pays quarterly dividends, so total return must exceed price return
    assert (1 + total).prod() > (1 + price).prod()


def test_finding5_days_to_earnings_uses_new_york_dates(store):
    from forwardstate.features import build_feature_snapshot

    # synthetic JPM results on 2024-04-15 (Mon, 07:00 ET); as of Fri 2024-04-12 23:59 ET
    _, feats = build_feature_snapshot(store, as_of_for_date(date(2024, 4, 12)), ["JPM"])
    days = feats.loc["JPM", "days_to_next_earnings"]
    assert days == 1

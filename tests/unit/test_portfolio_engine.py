"""AC-04: evaluate a valid portfolio against candidates; reject infeasible inputs clearly."""

from datetime import date
from pathlib import Path

import numpy as np
import pytest
import yaml
from fakes_risk import BootstrapForecaster

import forwardstate.portfolio.engine as pf_engine
from forwardstate.contracts import (
    CASH_ID,
    DECISION_BOUNDARY,
    Constraints,
    Holding,
    Portfolio,
    ScenarioAssumptions,
)
from forwardstate.pit import as_of_for_date
from forwardstate.portfolio import PortfolioEngine, solve_mean_variance
from forwardstate.testing import FixtureStore

ROOT = Path(__file__).resolve().parents[2]
AS_OF = as_of_for_date(date(2023, 6, 30))
A = ScenarioAssumptions()
BANKS = ["JPM", "BAC", "C", "MS", "GS"]


@pytest.fixture(scope="module")
def store():
    return FixtureStore()


@pytest.fixture(scope="module")
def engine(store):
    return PortfolioEngine(store, BootstrapForecaster(store))


@pytest.fixture()
def demo():
    return Portfolio(**yaml.safe_load((ROOT / "configs/portfolio.example.yaml").read_text()))


def with_constraints(p: Portfolio, **kw) -> Portfolio:
    return p.model_copy(update={"constraints": p.constraints.model_copy(update=kw)})


def codes(ev):
    return {i.code for i in ev.issues}


def test_valid_portfolio_is_evaluated_with_candidates(engine, demo):
    ev = engine.evaluate_portfolio(demo, AS_OF, A)
    assert ev.feasible and ev.issues == []
    assert ev.current is not None
    assert [c.label for c in ev.candidates] == [
        "No change", "Move 25% to cash", "Move 50% to cash", "Equal weight banks"]
    for alloc in [ev.current, *ev.candidates]:
        assert sum(alloc.weights.values()) == pytest.approx(1.0, abs=1e-6)  # weights sum to 100%
        q = {s.scenario.value: s for s in alloc.scenario_pnl}
        assert q["optimistic"].return_pct >= q["base"].return_pct >= q["pessimistic"].return_pct
        assert q["pessimistic"].pnl == pytest.approx(q["pessimistic"].return_pct * 100_000)
    m25 = ev.candidates[1]
    assert m25.weights[CASH_ID] == pytest.approx(0.325)
    assert m25.turnover == pytest.approx(0.45)
    assert m25.est_cost == pytest.approx(0.225 * 100_000 * 5 / 1e4)
    assert ev.candidates[3].weights["BAC"] == pytest.approx(0.18)
    # Moving to cash lowers simulated tail risk (correlated banks, cash has no price risk).
    assert ev.candidates[2].metrics.cvar_95 < ev.current.metrics.cvar_95
    assert set(ev.correlation) == set(BANKS) and ev.correlation["JPM"]["JPM"] == 1.0
    assert ev.correlation["JPM"]["BAC"] > 0.3  # sector correlation is kept
    assert ev.model_version.endswith("/pf1") and ev.disclaimer == DECISION_BOUNDARY
    assert any("not an instruction" in n for n in ev.candidates[1].notes)


def test_weights_not_summing_to_one_are_rejected(engine, demo):
    bad = demo.model_copy(update={"holdings": [
        Holding(security_id=h.security_id, weight=h.weight * 0.9) for h in demo.holdings]})
    ev = engine.evaluate_portfolio(bad, AS_OF, A)
    assert not ev.feasible and "weights_sum" in codes(ev)
    assert "90.00%" in ev.issues[0].message
    assert ev.candidates == []
    assert ev.current is not None  # still computable, with a note
    assert any("uninvested" in n for n in ev.current.notes)


def test_bounds_that_cannot_reach_100_percent(engine, demo):
    p = with_constraints(demo, max_position_weight=0.10, max_cash_weight=0.30)
    ev = engine.evaluate_portfolio(p, AS_OF, A)
    assert not ev.feasible and ev.candidates == []
    assert {"bounds_infeasible", "max_position"} <= codes(ev)
    msg = next(i.message for i in ev.issues if i.code == "bounds_infeasible")
    assert "80.0%" in msg  # 5 x 10% + 30%
    assert p.constraints.max_position_weight == 0.10  # never silently changed
    assert not engine.optimize(p, AS_OF, A).feasible


def test_benchmark_and_unknown_holdings_are_rejected(engine):
    p = Portfolio(total_value=1000, holdings=[
        Holding(security_id="SPY", weight=0.4), Holding(security_id="ZZZ", weight=0.3),
        Holding(security_id="JPM", weight=0.3)])
    ev = engine.evaluate_portfolio(p, AS_OF, A)
    assert not ev.feasible
    assert {"not_investable", "unknown_security"} <= codes(ev)
    assert "benchmark" in next(i.message for i in ev.issues if i.code == "not_investable")
    assert ev.current is None and ev.candidates == []


def test_cash_bounds_issues(engine, demo):
    ev = engine.evaluate_portfolio(with_constraints(demo, min_cash_weight=0.2), AS_OF, A)
    assert not ev.feasible and "cash_bounds" in codes(ev)


def test_candidate_that_breaks_a_constraint_is_left_out_not_clipped(engine, demo):
    ev = engine.evaluate_portfolio(with_constraints(demo, max_cash_weight=0.5), AS_OF, A)
    assert ev.feasible
    assert "Move 50% to cash" not in [c.label for c in ev.candidates]
    assert any("Move 50% to cash" in n and "maximum cash" in n for n in ev.current.notes)


def test_cash_is_not_assumed_free_of_return(engine):
    p = Portfolio(total_value=1000, holdings=[Holding(security_id=CASH_ID, weight=1.0)],
                  constraints=Constraints(cash_annual_yield=0.04))
    ev = engine.evaluate_portfolio(p, AS_OF, A)
    assert ev.current.metrics.expected_return == pytest.approx((1 + 0.04 / 252) ** 126 - 1)
    assert any("4.00% a year" in n for n in ev.current.notes)


def test_optimize_respects_constraints(engine, demo):
    p = with_constraints(demo, max_cash_weight=0.3, max_turnover=0.2, cash_annual_yield=0.04)
    ev = engine.optimize(p, AS_OF, A)
    assert ev.feasible, ev.issues
    labels = [c.label for c in ev.candidates]
    assert labels == ["No change", "Balanced", "Lower risk", "Return-seeking"]
    for c in ev.candidates:
        w = c.weights
        assert sum(w.values()) == pytest.approx(1.0, abs=1e-6)
        assert all(v <= 0.4 + 1e-7 for k, v in w.items() if k != CASH_ID)
        assert w.get(CASH_ID, 0) <= 0.3 + 1e-7
        assert c.turnover <= 0.2 + 1e-6
    er = {c.label: c.metrics.expected_return for c in ev.candidates}
    assert er["Return-seeking"] >= er["Balanced"] - 1e-9 >= er["Lower risk"] - 2e-9


def test_optimizer_failure_is_reported_never_relaxed(engine, demo, monkeypatch):
    class Failed:
        success = False
        message = "forced failure"
        x = None

    monkeypatch.setattr(pf_engine, "minimize", lambda *a, **k: Failed())
    ev = engine.optimize(demo, AS_OF, A)
    assert [c.label for c in ev.candidates] == ["No change"]
    assert sum(i.code == "optimizer_failed" for i in ev.issues) == 3
    assert "No relaxed result" in ev.issues[0].message


def test_solver_rejects_impossible_bounds():
    mu, sigma = np.array([0.01, 0.02]), np.eye(2) * 0.01
    w, err = solve_mean_variance(mu, sigma, 3.0, np.zeros(2), np.array([0.3, 0.3]),
                                 np.array([0.3, 0.3]), None)
    assert w is None and err


def test_simulation_failure_is_an_issue(store, demo):
    class Broken(BootstrapForecaster):
        def simulate_joint_returns(self, *a, **k):
            raise ValueError("no prices")

    ev = PortfolioEngine(store, Broken(store)).evaluate_portfolio(demo, AS_OF, A)
    assert not ev.feasible and "data_unavailable" in codes(ev) and ev.current is None


def test_deterministic(store, engine, demo):
    a = engine.evaluate_portfolio(demo, AS_OF, A)
    b = PortfolioEngine(store, BootstrapForecaster(store)).evaluate_portfolio(demo, AS_OF, A)
    assert a.model_dump() == b.model_dump()
    assert engine.optimize(demo, AS_OF, A).model_dump() == engine.optimize(demo, AS_OF, A).model_dump()

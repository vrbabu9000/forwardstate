"""Risk functions checked against cases you can work out by hand."""

import numpy as np
import pytest

from forwardstate.contracts import CASH_ID, Horizon
from forwardstate.risk import (
    compute_risk_metrics,
    concentration,
    correlation_dict,
    ledoit_wolf,
    median_max_drawdown,
    portfolio_horizon_returns,
    portfolio_values,
    var_cvar,
)


def test_constant_gain_path():
    paths = np.full((4, 10, 1), 0.001)
    m = compute_risk_metrics(paths, {"A": 1.0}, ["A"], Horizon.SHORT, 10)
    assert m.expected_return == pytest.approx(1.001**10 - 1)
    assert m.volatility == pytest.approx(0.0, abs=1e-15)
    assert m.var_95 == 0.0 and m.cvar_95 == 0.0
    assert m.max_drawdown_est == pytest.approx(0.0)
    assert m.prob_loss_exceeds == {"0.05": 0.0, "0.10": 0.0}
    assert m.concentration_hhi == 1.0 and m.largest_position == "A" and m.largest_weight == 1.0


def test_constant_loss_path():
    paths = np.full((4, 10, 1), -0.01)
    m = compute_risk_metrics(paths, {"A": 1.0}, ["A"], Horizon.SHORT, 10)
    loss = 1 - 0.99**10  # 9.56%
    assert m.expected_return == pytest.approx(-loss)
    assert m.var_95 == pytest.approx(loss)
    assert m.cvar_95 == pytest.approx(loss)
    assert m.max_drawdown_est == pytest.approx(loss)
    assert m.prob_loss_exceeds == {"0.05": 1.0, "0.10": 0.0}


def test_two_perfectly_correlated_assets():
    rng = np.random.default_rng(1)
    a = rng.normal(0.0, 0.01, size=(500, 20))
    paths = np.stack([a, a], axis=2)
    w = np.array([0.5, 0.5])
    port = portfolio_horizon_returns(paths, w)
    single = portfolio_horizon_returns(paths[:, :, :1], np.array([1.0]))
    np.testing.assert_allclose(port, single)  # no diversification when correlation is 1
    corr = correlation_dict(np.prod(1 + paths, axis=1) - 1, ["A", "B"])
    assert corr["A"]["B"] == pytest.approx(1.0)
    m = compute_risk_metrics(paths, {"A": 0.5, "B": 0.5}, ["A", "B"], Horizon.SHORT, 20)
    assert m.concentration_hhi == pytest.approx(0.5)


def test_cash_only_earns_the_stated_yield_whatever_the_simulator_says():
    noise = np.random.default_rng(2).normal(0, 0.05, size=(50, 20, 1))  # ignored for CASH
    m = compute_risk_metrics(noise, {CASH_ID: 1.0}, [CASH_ID], Horizon.SHORT, 20,
                             cash_annual_yield=0.0252)
    assert m.expected_return == pytest.approx(1.0001**20 - 1)
    assert m.volatility == pytest.approx(0.0, abs=1e-15)
    assert m.var_95 == 0.0 and m.cvar_95 == 0.0 and m.max_drawdown_est == 0.0
    assert m.concentration_hhi == 0.0 and m.largest_position is None and m.cash_weight == 1.0


def test_var_cvar_on_a_known_distribution():
    r = np.linspace(-0.10, 0.89, 100)  # -10%, -9%, ..., +89%
    var, cvar = var_cvar(r)
    assert var == pytest.approx(0.06)  # 5th worst
    assert cvar == pytest.approx(0.08)  # mean of the 5 worst


def test_drawdown_up_then_down():
    v = np.array([[1.0, 1.2, 0.9, 1.0]])
    assert median_max_drawdown(v) == pytest.approx(0.25)
    paths = np.array([[[0.2], [-0.25], [1 / 9]]])
    np.testing.assert_allclose(portfolio_values(paths, np.array([1.0])), v)


def test_concentration_excludes_cash():
    assert concentration({"A": 0.6, "B": 0.2, CASH_ID: 0.2}) == pytest.approx((0.4, "A", 0.6, 0.2))


def test_ledoit_wolf_matches_reference():
    sk = pytest.importorskip("sklearn.covariance")
    x = np.random.default_rng(3).normal(size=(60, 5)) @ np.diag([1, 2, 3, 4, 5])
    cov, shrink = ledoit_wolf(x)
    ref_cov, ref_shrink = sk.ledoit_wolf(x)
    np.testing.assert_allclose(cov, ref_cov, rtol=1e-10)
    assert shrink == pytest.approx(ref_shrink)
    assert 0 <= shrink <= 1

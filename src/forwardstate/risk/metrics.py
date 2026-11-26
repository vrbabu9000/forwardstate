"""Pure risk functions over simulated daily return paths (BRD p.7 PF-05, p.8 RISK-01).

Conventions
-----------
- ``paths`` has shape ``(n_paths, n_days, n_assets)`` and holds simple *daily* returns.
- ``weights`` is a 1-D array of start-of-horizon weights in the same asset order.
- Buy-and-hold: no rebalancing inside the horizon.
- CASH (when ``cash_index`` is given) earns ``cash_daily`` every day whatever the simulator put
  in that column. It is modelled with no price volatility; this is an assumption, not a claim
  that cash is risk-free.
- Losses are reported as positive fractions (0.05 = a 5% loss) and floored at 0.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

import numpy as np

from forwardstate.contracts import CASH_ID, Horizon, RiskMetrics

TAIL = 0.05  # 95% VaR / CVaR
DEFAULT_LOSS_LEVELS: tuple[float, ...] = (0.05, 0.10)


def loss_key(level: float) -> str:
    """Key used in ``RiskMetrics.prob_loss_exceeds``, e.g. 0.05 -> '0.05'."""
    return f"{level:.2f}"


def cash_daily_rate(cash_annual_yield: float) -> float:
    return float(cash_annual_yield) / 252.0


def apply_cash(paths: np.ndarray, cash_index: int | None, cash_daily: float) -> np.ndarray:
    """Return ``paths`` with the CASH column set to the constant daily cash rate."""
    if cash_index is None:
        return paths
    out = np.array(paths, dtype=float, copy=True)
    out[:, :, cash_index] = cash_daily
    return out


def asset_horizon_returns(
    paths: np.ndarray, cash_index: int | None = None, cash_daily: float = 0.0
) -> np.ndarray:
    """Compounded return of each asset over the horizon, shape (n_paths, n_assets)."""
    p = apply_cash(np.asarray(paths, dtype=float), cash_index, cash_daily)
    return np.prod(1.0 + p, axis=1) - 1.0


def portfolio_values(
    paths: np.ndarray, weights: np.ndarray, cash_index: int | None = None, cash_daily: float = 0.0
) -> np.ndarray:
    """Buy-and-hold portfolio value per path and day, starting at sum(weights).

    Shape (n_paths, n_days + 1); column 0 is the start value.
    """
    p = apply_cash(np.asarray(paths, dtype=float), cash_index, cash_daily)
    w = np.asarray(weights, dtype=float)
    growth = np.cumprod(1.0 + p, axis=1)  # (paths, days, assets)
    vals = np.einsum("pda,a->pd", growth, w)  # (paths, days)
    start = np.full((vals.shape[0], 1), w.sum())
    return np.concatenate([start, vals], axis=1)


def portfolio_horizon_returns(
    paths: np.ndarray, weights: np.ndarray, cash_index: int | None = None, cash_daily: float = 0.0
) -> np.ndarray:
    """Portfolio return over the horizon per path, shape (n_paths,)."""
    x = asset_horizon_returns(paths, cash_index, cash_daily)
    return np.einsum("pa,a->p", x, np.asarray(weights, dtype=float))


def var_cvar(returns: np.ndarray, tail: float = TAIL) -> tuple[float, float]:
    """(VaR, CVaR) as positive loss fractions, floored at 0.

    Deterministic tail: the worst ``ceil(tail * n)`` outcomes. VaR is the best of those,
    CVaR their mean.
    """
    r = np.sort(np.asarray(returns, dtype=float))
    if r.size == 0:
        return 0.0, 0.0
    k = max(1, math.ceil(tail * r.size))
    worst = r[:k]
    return max(0.0, -float(worst[-1])), max(0.0, -float(worst.mean()))


def prob_loss_exceeds(returns: np.ndarray, level: float) -> float:
    """Simulated share of paths losing more than ``level`` (uncalibrated)."""
    r = np.asarray(returns, dtype=float)
    return float(np.mean(r < -level)) if r.size else 0.0


def median_max_drawdown(values: np.ndarray) -> float:
    """Median over paths of the largest peak-to-trough fall, positive fraction."""
    v = np.asarray(values, dtype=float)
    peak = np.maximum.accumulate(v, axis=1)
    with np.errstate(divide="ignore", invalid="ignore"):
        dd = np.where(peak > 0, 1.0 - v / peak, 0.0)
    return max(0.0, float(np.median(dd.max(axis=1))))


def concentration(weights: dict[str, float]) -> tuple[float, str | None, float, float]:
    """(HHI, largest position, its weight, cash weight).

    HHI and the largest position are over securities only (CASH excluded): holding cash is not
    concentration risk. A cash-only portfolio has HHI 0 and no largest position.
    """
    cash = float(weights.get(CASH_ID, 0.0))
    risky = {k: float(v) for k, v in weights.items() if k != CASH_ID and v > 0}
    if not risky:
        return 0.0, None, 0.0, cash
    hhi = float(sum(v * v for v in risky.values()))
    largest = max(sorted(risky), key=lambda k: risky[k])
    return hhi, largest, risky[largest], cash


def ledoit_wolf(x: np.ndarray) -> tuple[np.ndarray, float]:
    """Ledoit-Wolf (2004) shrinkage of the sample covariance towards a scaled identity.

    ``x`` has shape (n_samples, n_features). Returns (shrunk covariance, shrinkage in [0, 1]).
    Matches ``sklearn.covariance.ledoit_wolf`` (biased 1/n sample covariance).
    """
    x = np.asarray(x, dtype=float)
    n, p = x.shape
    if n < 2 or p == 0:
        return np.zeros((p, p)), 0.0
    xc = x - x.mean(axis=0)
    emp = xc.T @ xc / n
    mu = float(np.trace(emp)) / p
    x2 = xc**2
    beta_ = float(np.sum(x2.T @ x2))
    delta_ = float(np.sum((xc.T @ xc) ** 2)) / n**2
    beta = (beta_ / n - delta_) / (p * n)
    delta = (delta_ - 2.0 * mu * float(np.trace(emp)) + p * mu**2) / p
    beta = min(beta, delta)
    shrink = 0.0 if delta <= 0 else max(0.0, beta / delta)
    cov = (1.0 - shrink) * emp
    cov[np.diag_indices(p)] += shrink * mu
    return cov, shrink


def correlation_dict(x: np.ndarray, ids: Sequence[str]) -> dict[str, dict[str, float]]:
    """Sample correlation of simulated horizon returns. Zero-variance columns get 0 off-diagonal."""
    x = np.asarray(x, dtype=float)
    sd = x.std(axis=0)
    xc = x - x.mean(axis=0)
    cov = xc.T @ xc / max(len(x), 1)
    out: dict[str, dict[str, float]] = {}
    for i, a in enumerate(ids):
        row: dict[str, float] = {}
        for j, b in enumerate(ids):
            if i == j:
                row[b] = 1.0
            elif sd[i] > 1e-12 and sd[j] > 1e-12:
                row[b] = round(float(np.clip(cov[i, j] / (sd[i] * sd[j]), -1, 1)), 6)
            else:
                row[b] = 0.0
        out[a] = row
    return out


def scenario_quantiles(returns: np.ndarray) -> dict[str, float]:
    """Portfolio return quantiles used for scenarios: 0.9 optimistic, 0.5 base, 0.1 pessimistic."""
    r = np.asarray(returns, dtype=float)
    return {
        "optimistic": float(np.quantile(r, 0.9)),
        "base": float(np.quantile(r, 0.5)),
        "pessimistic": float(np.quantile(r, 0.1)),
    }


def compute_risk_metrics(
    paths: np.ndarray,
    weights: dict[str, float],
    ids: Sequence[str],
    horizon: Horizon,
    horizon_days: int,
    cash_annual_yield: float = 0.0,
    loss_levels: Sequence[float] = DEFAULT_LOSS_LEVELS,
) -> RiskMetrics:
    """All RiskMetrics for one weight vector over one set of simulated paths."""
    ids = list(ids)
    w = np.array([float(weights.get(s, 0.0)) for s in ids])
    cash_index = ids.index(CASH_ID) if CASH_ID in ids else None
    cd = cash_daily_rate(cash_annual_yield)
    vals = portfolio_values(paths, w, cash_index, cd)
    rets = vals[:, -1] - vals[:, 0]
    var95, cvar95 = var_cvar(rets)
    hhi, largest, largest_w, cash_w = concentration(weights)
    return RiskMetrics(
        horizon=horizon,
        horizon_trading_days=horizon_days,
        expected_return=float(rets.mean()),
        volatility=float(rets.std(ddof=1)) if rets.size > 1 else 0.0,
        var_95=var95,
        cvar_95=cvar95,
        max_drawdown_est=median_max_drawdown(vals),
        prob_loss_exceeds={loss_key(lv): prob_loss_exceeds(rets, lv) for lv in loss_levels},
        concentration_hhi=hhi,
        largest_position=largest,
        largest_weight=largest_w,
        cash_weight=cash_w,
    )

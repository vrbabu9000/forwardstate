"""PortfolioEngine: evaluates a portfolio and builds candidate allocations (BRD p.7, AC-04).

Decision support only. Candidates are options for comparison, never instructions. Nothing here
trades, routes orders or moves money.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import numpy as np
from scipy.optimize import minimize

import forwardstate
from forwardstate.contracts import (
    CASH_ID,
    DEFAULT_HORIZON_DAYS,
    Allocation,
    Constraints,
    FeasibilityIssue,
    Horizon,
    Portfolio,
    PortfolioEvaluation,
    RiskMetrics,
    ScenarioAssumptions,
    ScenarioName,
    ScenarioPnL,
    stable_hash,
)
from forwardstate.pit import ensure_utc
from forwardstate.risk import (
    asset_horizon_returns,
    cash_daily_rate,
    compute_risk_metrics,
    correlation_dict,
    ledoit_wolf,
    portfolio_horizon_returns,
    scenario_quantiles,
)
from forwardstate.services import ForecastService, PointInTimeStore

from .feasibility import BLOCKING_CODES, TOL, check_feasibility, investable_universe

MODEL_VERSION = f"{forwardstate.__version__}/pf1"
OPTION_NOTE = "An option for comparison, not an instruction. You decide whether to act."


class DataUnavailable(RuntimeError):
    """Raised when the simulator cannot produce usable paths (missing or bad data)."""


def seed_from(*parts: object) -> int:
    return int(stable_hash(list(parts))[:8], 16)


def cash_note(c: Constraints) -> str:
    return (
        f"Cash is assumed to earn {c.cash_annual_yield:.2%} a year (constraints.cash_annual_yield) "
        "with no price movement. Real cash equivalents still carry some risk."
    )


@dataclass
class Simulation:
    """Simulated daily paths for ``ids`` over one horizon, plus helpers."""

    ids: list[str]
    paths: np.ndarray
    horizon: Horizon
    horizon_days: int
    cash_annual_yield: float

    @property
    def cash_index(self) -> int | None:
        return self.ids.index(CASH_ID) if CASH_ID in self.ids else None

    def vector(self, weights: dict[str, float]) -> np.ndarray:
        return np.array([float(weights.get(s, 0.0)) for s in self.ids])

    def asset_returns(self) -> np.ndarray:
        return asset_horizon_returns(
            self.paths, self.cash_index, cash_daily_rate(self.cash_annual_yield)
        )

    def portfolio_returns(self, weights: dict[str, float]) -> np.ndarray:
        return portfolio_horizon_returns(
            self.paths, self.vector(weights), self.cash_index,
            cash_daily_rate(self.cash_annual_yield),
        )

    def metrics(self, weights: dict[str, float]) -> RiskMetrics:
        return compute_risk_metrics(
            self.paths, weights, self.ids, self.horizon, self.horizon_days, self.cash_annual_yield
        )

    def correlation(self) -> dict[str, dict[str, float]]:
        risky = [i for i, s in enumerate(self.ids) if s != CASH_ID]
        return correlation_dict(self.asset_returns()[:, risky], [self.ids[i] for i in risky])


def turnover(a: dict[str, float], b: dict[str, float]) -> float:
    """Sum of absolute weight changes over all positions, cash included (0..2 scale)."""
    keys = set(a) | set(b)
    return float(sum(abs(a.get(k, 0.0) - b.get(k, 0.0)) for k in keys))


def trading_cost(a: dict[str, float], b: dict[str, float], value: float, bps: float) -> float:
    """Estimated cost in currency: bps on the value of securities traded (cash leg is free)."""
    keys = (set(a) | set(b)) - {CASH_ID}
    traded = sum(abs(a.get(k, 0.0) - b.get(k, 0.0)) for k in keys)
    return float(traded * value * bps / 1e4)


def move_to_cash(weights: dict[str, float], fraction: float) -> dict[str, float]:
    """Move ``fraction`` of every security position to cash, pro rata."""
    out = {k: v * (1 - fraction) for k, v in weights.items() if k != CASH_ID}
    moved = sum(v * fraction for k, v in weights.items() if k != CASH_ID)
    out[CASH_ID] = weights.get(CASH_ID, 0.0) + moved
    return out


def constraint_violations(w: dict[str, float], c: Constraints, current: dict[str, float]) -> list[str]:
    """Plain-English list of the user's constraints that ``w`` breaks (empty = fine)."""
    out = []
    for k, v in sorted(w.items()):
        if k != CASH_ID and v > c.max_position_weight + TOL:
            out.append(f"{k} would be {v:.1%}, above the maximum position {c.max_position_weight:.1%}")
    cash = w.get(CASH_ID, 0.0)
    if cash > c.max_cash_weight + TOL:
        out.append(f"cash would be {cash:.1%}, above the maximum cash {c.max_cash_weight:.1%}")
    if cash < c.min_cash_weight - TOL:
        out.append(f"cash would be {cash:.1%}, below the minimum cash {c.min_cash_weight:.1%}")
    if c.max_turnover is not None:
        t = turnover(w, current)
        if t > c.max_turnover + TOL:
            out.append(f"turnover would be {t:.1%}, above the maximum turnover {c.max_turnover:.1%}")
    return out


def clean(w: dict[str, float]) -> dict[str, float]:
    return {k: round(float(v), 10) for k, v in w.items() if v > 1e-9}


class PortfolioEngine:
    """Implements ``forwardstate.services.PortfolioService``."""

    model_version = MODEL_VERSION

    def __init__(
        self,
        store: PointInTimeStore,
        forecaster: ForecastService,
        n_paths: int = 2000,
        horizon_days: dict[Horizon, int] | None = None,
    ) -> None:
        self.store = store
        self.forecaster = forecaster
        self.n_paths = n_paths
        self.horizon_days = dict(horizon_days or DEFAULT_HORIZON_DAYS)

    # ---- building blocks (also used by the alert engine) ------------------------------
    def universe(self) -> list[str]:
        return investable_universe(self.store.securities())

    def feasibility(self, portfolio: Portfolio) -> list[FeasibilityIssue]:
        return check_feasibility(portfolio, self.store.securities())

    def simulate(
        self,
        ids: list[str],
        as_of: datetime,
        horizon: Horizon,
        assumptions: ScenarioAssumptions,
        cash_annual_yield: float,
        n_paths: int | None = None,
    ) -> Simulation:
        """Joint simulated paths from the forecaster. Raises DataUnavailable on bad output."""
        as_of = ensure_utc(as_of)
        n = n_paths or self.n_paths
        days = self.horizon_days[horizon]
        seed = seed_from("pf-sim", as_of, ids, days, assumptions, n)
        try:
            paths = self.forecaster.simulate_joint_returns(
                as_of, list(ids), days, assumptions, n_paths=n, seed=seed
            )
        except Exception as exc:  # the simulator failure is reported, not hidden
            raise DataUnavailable(f"Simulation failed: {exc}") from exc
        paths = np.asarray(paths, dtype=float)
        if paths.shape != (n, days, len(ids)):
            raise DataUnavailable(
                f"Simulation returned shape {paths.shape}, expected {(n, days, len(ids))}."
            )
        risky = [i for i, s in enumerate(ids) if s != CASH_ID]
        if not np.all(np.isfinite(paths[:, :, risky])):
            raise DataUnavailable("Simulation returned missing values (not enough price history).")
        return Simulation(list(ids), paths, horizon, days, cash_annual_yield)

    def allocation(
        self,
        label: str,
        weights: dict[str, float],
        sim: Simulation,
        portfolio: Portfolio,
        notes: list[str] | None = None,
    ) -> Allocation:
        current = {h.security_id: h.weight for h in portfolio.holdings}
        r = sim.portfolio_returns(weights)
        q = scenario_quantiles(r)
        v = portfolio.total_value
        pnl = [
            ScenarioPnL(scenario=ScenarioName(name), return_pct=ret, pnl=ret * v)
            for name, ret in q.items()
        ]
        return Allocation(
            label=label,
            weights=clean(weights),
            metrics=sim.metrics(weights),
            scenario_pnl=pnl,
            turnover=turnover(weights, current),
            est_cost=trading_cost(weights, current, v, portfolio.constraints.transaction_cost_bps),
            notes=list(notes or []),
        )

    # ---- PortfolioService ---------------------------------------------------------------
    def evaluate_portfolio(
        self, portfolio: Portfolio, as_of: datetime, assumptions: ScenarioAssumptions
    ) -> PortfolioEvaluation:
        return self._run("evaluate", portfolio, as_of, assumptions)

    def optimize(
        self, portfolio: Portfolio, as_of: datetime, assumptions: ScenarioAssumptions
    ) -> PortfolioEvaluation:
        return self._run("optimize", portfolio, as_of, assumptions)

    # ---- internals ----------------------------------------------------------------------
    def _run(
        self, kind: str, portfolio: Portfolio, as_of: datetime, assumptions: ScenarioAssumptions
    ) -> PortfolioEvaluation:
        as_of = ensure_utc(as_of)
        input_hash = stable_hash({
            "kind": kind, "portfolio": portfolio, "as_of": as_of, "assumptions": assumptions,
            "n_paths": self.n_paths, "horizon_days": self.horizon_days,
            "model_version": MODEL_VERSION,
        })
        issues = self.feasibility(portfolio)
        c = portfolio.constraints
        weights = {h.security_id: h.weight for h in portfolio.holdings}
        current: Allocation | None = None
        candidates: list[Allocation] = []
        corr: dict[str, dict[str, float]] = {}

        if not any(i.code in BLOCKING_CODES for i in issues):
            try:
                sim = self.simulate(
                    self.universe(), as_of, portfolio.horizon, assumptions, c.cash_annual_yield
                )
            except DataUnavailable as exc:
                issues.append(FeasibilityIssue(code="data_unavailable", message=str(exc)))
            else:
                notes = [cash_note(c), "Simulated, not calibrated."]
                total = sum(weights.values())
                if abs(total - 1) > TOL:
                    notes.append(
                        f"Weights add up to {total:.2%}; metrics use them as entered, with the "
                        "rest treated as uninvested at zero return."
                    )
                current = self.allocation("current", weights, sim, portfolio, notes)
                corr = sim.correlation()
                if not issues:
                    if kind == "evaluate":
                        candidates = self._rule_candidates(portfolio, sim, current)
                    else:
                        candidates = self._optimized_candidates(portfolio, sim, issues)

        feasible = not any(i.code != "optimizer_failed" for i in issues)
        return PortfolioEvaluation(
            run_id=f"{kind}-{input_hash[:12]}",
            as_of=as_of,
            portfolio_id=portfolio.portfolio_id,
            feasible=feasible,
            issues=issues,
            current=current,
            candidates=candidates if feasible else [],
            correlation=corr,
            model_version=MODEL_VERSION,
            input_hash=input_hash,
        )

    def _rule_candidates(
        self, portfolio: Portfolio, sim: Simulation, current: Allocation
    ) -> list[Allocation]:
        c = portfolio.constraints
        w0 = {h.security_id: h.weight for h in portfolio.holdings}
        banks = [s for s in sim.ids if s != CASH_ID]
        cash = w0.get(CASH_ID, 0.0)
        equal = {s: (1 - cash) / len(banks) for s in banks} | {CASH_ID: cash}
        options = [
            ("No change", dict(w0), "Keep the current weights."),
            ("Move 25% to cash", move_to_cash(w0, 0.25),
             "Each security position is cut by 25% (pro rata) and the proceeds held as cash."),
            ("Move 50% to cash", move_to_cash(w0, 0.50),
             "Each security position is cut by 50% (pro rata) and the proceeds held as cash."),
            ("Equal weight banks", equal,
             "Securities spread equally across the five banks; cash weight unchanged."),
        ]
        out = []
        for label, w, note in options:
            broken = constraint_violations(w, c, w0)
            if broken:
                current.notes.append(f"'{label}' not shown: " + "; ".join(broken) + ".")
                continue
            out.append(self.allocation(label, w, sim, portfolio, [note, OPTION_NOTE, cash_note(c)]))
        return out

    def _optimized_candidates(
        self, portfolio: Portfolio, sim: Simulation, issues: list[FeasibilityIssue]
    ) -> list[Allocation]:
        c = portfolio.constraints
        w0 = {h.security_id: h.weight for h in portfolio.holdings}
        x = sim.asset_returns()
        mu = x.mean(axis=0)
        sigma, shrink = ledoit_wolf(x)
        ids = sim.ids
        lb = np.array([c.min_cash_weight if s == CASH_ID else 0.0 for s in ids])
        ub = np.array([c.max_cash_weight if s == CASH_ID else c.max_position_weight for s in ids])
        base_notes = [
            (f"Long-only mean-variance (scipy SLSQP) on {len(x)} simulated {sim.horizon_days}-day "
            f"returns; covariance shrunk {shrink:.1%} towards a scaled identity (Ledoit-Wolf)."),
            OPTION_NOTE,
            cash_note(c),
        ]
        out = [self.allocation("No change", dict(w0), sim, portfolio,
                               ["Keep the current weights.", OPTION_NOTE, cash_note(c)])]
        lam = c.risk_aversion
        for label, lam_i in (("Balanced", lam), ("Lower risk", lam * 4), ("Return-seeking", lam / 4)):
            w, err = solve_mean_variance(mu, sigma, lam_i, lb, ub, sim.vector(w0), c.max_turnover)
            if w is None:
                issues.append(FeasibilityIssue(
                    code="optimizer_failed",
                    message=f"The optimizer could not find a '{label}' allocation within your "
                    f"constraints ({err}). No relaxed result is shown.",
                ))
                continue
            wd = dict(zip(ids, w.tolist()))
            out.append(self.allocation(
                label, wd, sim, portfolio, [f"Risk aversion λ = {lam_i:g}.", *base_notes]
            ))
        return out


def solve_mean_variance(
    mu: np.ndarray,
    sigma: np.ndarray,
    lam: float,
    lb: np.ndarray,
    ub: np.ndarray,
    w0: np.ndarray,
    max_turnover: float | None,
) -> tuple[np.ndarray | None, str]:
    """maximise mu'w - (lam/2) w'Σw  s.t. sum w = 1, lb <= w <= ub, sum|w - w0| <= max_turnover.

    Returns (weights, "") or (None, reason). The result is checked against every constraint;
    a result that breaks one is rejected, never relaxed.
    """
    n = len(mu)
    use_t = max_turnover is not None

    def split(x: np.ndarray) -> np.ndarray:
        return x[:n]

    def f(x: np.ndarray) -> float:
        w = split(x)
        return float(-(mu @ w) + 0.5 * lam * w @ sigma @ w)

    def g(x: np.ndarray) -> np.ndarray:
        w = split(x)
        grad = -mu + lam * sigma @ w
        return np.concatenate([grad, np.zeros(n)]) if use_t else grad

    cons: list[dict] = [{
        "type": "eq",
        "fun": lambda x: np.sum(split(x)) - 1.0,
        "jac": lambda x: np.concatenate([np.ones(n), np.zeros(n)]) if use_t else np.ones(n),
    }]
    bounds = list(zip(lb.tolist(), ub.tolist()))
    x0 = np.clip(w0, lb, ub)
    if use_t:
        eye = np.eye(n)
        cons += [
            {"type": "ineq", "fun": lambda x: x[n:] - (x[:n] - w0),
             "jac": lambda x: np.hstack([-eye, eye])},
            {"type": "ineq", "fun": lambda x: x[n:] + (x[:n] - w0),
             "jac": lambda x: np.hstack([eye, eye])},
            {"type": "ineq", "fun": lambda x: max_turnover - np.sum(x[n:]),
             "jac": lambda x: np.concatenate([np.zeros(n), -np.ones(n)])},
        ]
        bounds += [(0.0, 2.0)] * n
        x0 = np.concatenate([x0, np.abs(x0 - w0)])
    res = minimize(f, x0, jac=g, bounds=bounds, constraints=cons, method="SLSQP",
                   options={"maxiter": 500, "ftol": 1e-12})
    if not res.success:
        return None, res.message
    w = split(res.x).copy()
    if np.any(w < lb - 1e-7) or np.any(w > ub + 1e-7):
        return None, "result breaks a weight bound"
    w = np.clip(w, lb, ub)
    if abs(w.sum() - 1.0) > TOL:
        return None, "weights do not add up to 100%"
    if use_t and float(np.abs(w - w0).sum()) > max_turnover + TOL:
        return None, "result breaks the turnover limit"
    return w, ""

"""Portfolio, constraints, risk metrics and candidate allocations (BRD p.7)."""

from __future__ import annotations

from pydantic import AwareDatetime, Field, field_validator

from .common import DECISION_BOUNDARY, Horizon, Model
from .forecasts import ScenarioName

CASH_ID = "CASH"


class Holding(Model):
    security_id: str
    weight: float = Field(ge=0, le=1, description="Fraction of portfolio value. Long-only MVP.")


class Constraints(Model):
    """MVP defaults: long-only, no leverage, no shorting, USD (BRD p.7)."""

    max_position_weight: float = Field(default=0.40, gt=0, le=1)
    min_cash_weight: float = Field(default=0.0, ge=0, le=1)
    max_cash_weight: float = Field(default=1.0, ge=0, le=1)
    max_turnover: float | None = Field(default=None, ge=0, le=2)
    risk_aversion: float = Field(default=3.0, ge=0)
    cash_annual_yield: float = Field(default=0.0, description="Decimal. Not assumed zero-risk.")
    transaction_cost_bps: float = Field(default=5.0, ge=0)
    long_only: bool = True
    allow_leverage: bool = False

    @field_validator("long_only")
    @classmethod
    def _long_only(cls, v: bool) -> bool:
        if not v:
            raise ValueError("Shorting is out of MVP scope (long-only).")
        return v

    @field_validator("allow_leverage")
    @classmethod
    def _no_leverage(cls, v: bool) -> bool:
        if v:
            raise ValueError("Leverage is out of MVP scope.")
        return v


class Portfolio(Model):
    portfolio_id: str = "default"
    name: str = "My portfolio"
    base_currency: str = "USD"
    total_value: float = Field(gt=0)
    holdings: list[Holding]
    horizon: Horizon = Horizon.MEDIUM
    constraints: Constraints = Field(default_factory=Constraints)


class RiskMetrics(Model):
    horizon: Horizon
    horizon_trading_days: int
    expected_return: float = Field(description="Decimal over the horizon.")
    volatility: float = Field(description="Std. dev. of horizon return, decimal.")
    var_95: float = Field(description="95% Value-at-Risk as a positive loss fraction.")
    cvar_95: float = Field(description="Expected loss in the worst 5% (CVaR), positive fraction.")
    max_drawdown_est: float = Field(description="Median simulated max drawdown, positive fraction.")
    prob_loss_exceeds: dict[str, float] = Field(
        default_factory=dict, description="e.g. {'0.05': 0.18}: P(loss > 5%) — simulated, uncalibrated."
    )
    concentration_hhi: float
    largest_position: str | None = None
    largest_weight: float = 0.0
    cash_weight: float = 0.0


class ScenarioPnL(Model):
    scenario: ScenarioName
    return_pct: float = Field(description="Decimal, 0.05 = 5%.")
    pnl: float = Field(description="In base currency.")


class Allocation(Model):
    label: str = Field(description="'current', 'no change', 'balanced', 'min risk', 'defensive'...")
    weights: dict[str, float]
    metrics: RiskMetrics
    scenario_pnl: list[ScenarioPnL] = Field(default_factory=list)
    turnover: float = 0.0
    est_cost: float = 0.0
    notes: list[str] = Field(default_factory=list)


class FeasibilityIssue(Model):
    code: str = Field(description="e.g. 'weights_sum', 'max_position', 'cash_bounds', 'unknown_security'.")
    message: str
    field: str | None = None


class PortfolioEvaluation(Model):
    run_id: str
    as_of: AwareDatetime
    portfolio_id: str
    feasible: bool
    issues: list[FeasibilityIssue] = Field(default_factory=list)
    current: Allocation | None = None
    candidates: list[Allocation] = Field(default_factory=list)
    correlation: dict[str, dict[str, float]] = Field(default_factory=dict)
    model_version: str
    input_hash: str
    disclaimer: str = DECISION_BOUNDARY

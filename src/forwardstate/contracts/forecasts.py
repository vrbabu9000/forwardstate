"""Scenario assumptions and forecasts (BRD p.6)."""

from __future__ import annotations

from enum import Enum

from pydantic import AwareDatetime, Field

from .common import Confidence, Horizon, Model


class ScenarioName(str, Enum):
    OPTIMISTIC = "optimistic"
    BASE = "base"
    PESSIMISTIC = "pessimistic"


class ScenarioAssumptions(Model):
    """User-editable assumptions (AC-02). Zero/neutral defaults mean 'history only'."""

    rate_change_bps: float = Field(default=0.0, description="Assumed Fed funds change, basis points.")
    earnings_surprise_pct: float = Field(
        default=0.0, description="Assumed next-earnings surprise vs expectations, percent."
    )
    market_return_shift_pct: float = Field(
        default=0.0, description="Shift to the annualised market (benchmark) return, percent."
    )
    volatility_multiplier: float = Field(default=1.0, gt=0, description="Scales historical volatility.")
    analyst_weight: float = Field(
        default=0.25, ge=0, le=1, description="Weight on analyst targets vs history in the base case."
    )
    lookback_years: float = Field(default=5.0, gt=0, le=25)
    notes: str | None = None


class ScenarioForecast(Model):
    scenario: ScenarioName
    quantile: float = Field(description="Quantile of the return distribution this scenario uses.")
    projected_return: float = Field(description="Price return over the horizon, decimal.")
    projected_price: float
    interval_low: float = Field(description="Lower price bound of the stated interval.")
    interval_high: float
    interval_coverage: float = Field(description="Nominal coverage, e.g. 0.8 for a 10-90% band.")
    probability: float | None = Field(default=None, description="Only if calibrated (Phase 2).")
    assumptions_applied: list[str] = Field(default_factory=list)


class SecurityForecast(Model):
    security_id: str
    horizon: Horizon
    horizon_trading_days: int
    return_type: str = "price"  # price return, not total return
    start_price: float | None
    start_date: str | None = None
    scenarios: list[ScenarioForecast] = Field(default_factory=list)
    status: Confidence
    status_reason: str | None = None
    method: str
    model_version: str
    feature_snapshot_id: str | None = None
    sample_size: int = 0
    drivers: dict[str, float] = Field(
        default_factory=dict, description="Named contributions to the base-case return."
    )


class ForecastRun(Model):
    run_id: str
    as_of: AwareDatetime
    data_cutoff: AwareDatetime
    security_ids: list[str]
    horizons: list[Horizon]
    assumptions: ScenarioAssumptions
    forecasts: list[SecurityForecast]
    model_version: str
    input_hash: str
    created_at: AwareDatetime

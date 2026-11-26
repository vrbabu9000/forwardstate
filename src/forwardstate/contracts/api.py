"""Request/response shapes used by the HTTP API (docs/api.md) and the frontend."""

from __future__ import annotations

from datetime import date
from enum import Enum
from typing import Any

from pydantic import AwareDatetime, Field

from .alerts import AlertRule, AlertStatus
from .common import CONTRACT_VERSION, DECISION_BOUNDARY, DataMode, DataOrigin, Horizon, Model
from .forecasts import ScenarioAssumptions
from .portfolio import Constraints, Portfolio


class Meta(Model):
    app: str = "ForwardState"
    version: str
    contract_version: str = CONTRACT_VERSION
    mode: DataMode = DataMode.REPLAY
    data_origin: DataOrigin = Field(description="'real' when the Yahoo cache is loaded, else 'synthetic'.")
    sector: str = "financials"
    disclaimer: str = DECISION_BOUNDARY


class PricePoint(Model):
    date: date
    close: float = Field(description="Adjusted close as of the query.")
    raw_close: float
    volume: float | None = None


class PriceSeries(Model):
    security_id: str
    as_of: AwareDatetime
    origin: DataOrigin
    points: list[PricePoint]


class RebasedPoint(Model):
    date: date
    value: float = Field(description="Rebased to 100 at the first common date.")


class PeerSeries(Model):
    security_id: str
    points: list[RebasedPoint]
    total_return: float
    volatility_annual: float
    max_drawdown: float


class PeerComparison(Model):
    focal_id: str
    base_date: date | None
    as_of: AwareDatetime
    series: list[PeerSeries]


class ForecastRequest(Model):
    as_of: AwareDatetime | None = Field(default=None, description="Default: latest data.")
    security_ids: list[str]
    horizons: list[Horizon] = Field(default_factory=lambda: list(Horizon))
    assumptions: ScenarioAssumptions = Field(default_factory=ScenarioAssumptions)


class PortfolioRequest(Model):
    as_of: AwareDatetime | None = None
    portfolio: Portfolio
    assumptions: ScenarioAssumptions = Field(default_factory=ScenarioAssumptions)


class AlertsRequest(Model):
    as_of: AwareDatetime | None = None
    portfolio: Portfolio
    rule_ids: list[str] | None = None
    assumptions: ScenarioAssumptions = Field(default_factory=ScenarioAssumptions)


class ReplayRequest(Model):
    portfolio: Portfolio
    start: date
    end: date
    step_trading_days: int = Field(default=1, ge=1, le=20)
    rule_ids: list[str] | None = None
    assumptions: ScenarioAssumptions = Field(default_factory=ScenarioAssumptions)


class TransitionRequest(Model):
    to_status: AlertStatus
    note: str | None = None


class Settings(Model):
    horizon_days: dict[Horizon, int]
    constraints: Constraints
    assumptions: ScenarioAssumptions
    alert_rules: list[AlertRule]
    default_portfolio: Portfolio


class RunKind(str, Enum):
    FORECAST = "forecast"
    PORTFOLIO = "portfolio"
    OPTIMIZE = "optimize"
    ALERTS = "alerts"
    REPLAY = "replay"


class RunRecord(Model):
    run_id: str
    kind: RunKind
    created_at: AwareDatetime
    as_of: AwareDatetime | None
    data_cutoff: AwareDatetime | None = None
    model_version: str
    contract_version: str = CONTRACT_VERSION
    config_hash: str
    input_hash: str
    output_hash: str
    request: dict[str, Any] = Field(description="The exact request, so the run can be reproduced.")
    data_origin: DataOrigin
    source_status: list[dict[str, Any]] = Field(default_factory=list)


class ReproduceResult(Model):
    run_id: str
    reproduced_run_id: str
    original_output_hash: str
    reproduced_output_hash: str
    match: bool
    note: str | None = None

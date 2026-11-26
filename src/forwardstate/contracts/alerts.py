"""Alert rules, alerts, lifecycle and replay (BRD p.8)."""

from __future__ import annotations

from datetime import date
from enum import Enum

from pydantic import AwareDatetime, Field

from .common import DECISION_BOUNDARY, Confidence, DataOrigin, Horizon, Model
from .portfolio import RiskMetrics


class AlertSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    HIGH = "high"
    CRITICAL = "critical"


class AlertStatus(str, Enum):
    NEW = "new"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"
    SUPERSEDED = "superseded"


class AlertMetric(str, Enum):
    FORECAST_DRAWDOWN = "forecast_drawdown"  # simulated loss over horizon (CVaR-style)
    DOWNSIDE_PROBABILITY = "downside_probability"  # P(loss > x)
    REALIZED_LOSS = "realized_loss"  # actual trailing loss
    CONCENTRATION = "concentration"
    EVENT_SEVERITY = "event_severity"  # an event with |abnormal return| above threshold


class AlertRule(Model):
    rule_id: str
    version: int = 1
    description: str
    metric: AlertMetric
    horizon: Horizon = Horizon.SHORT
    threshold: float
    loss_level: float | None = Field(default=None, description="Loss x for DOWNSIDE_PROBABILITY.")
    lookback_trading_days: int | None = Field(default=None, description="For REALIZED_LOSS.")
    severity: AlertSeverity = AlertSeverity.WARNING
    cooldown_trading_days: int = 5
    enabled: bool = True


class EvidenceItem(Model):
    kind: str = Field(description="'event', 'analyst', 'price', 'macro', 'model'.")
    ref_id: str
    label: str
    at: AwareDatetime | None = None
    origin: DataOrigin = DataOrigin.REAL
    url: str | None = None


class ActionOption(Model):
    """A candidate response. Never an instruction."""

    label: str = Field(description="e.g. 'Hold (no change)', 'Move 25% to cash'.")
    weights: dict[str, float]
    expected_return: float
    cvar_95: float
    projected_loss: float = Field(description="Scenario loss in currency (positive = loss).")
    est_cost: float = 0.0
    missed_upside: float = Field(
        default=0.0, description="Upside given up in the optimistic case, in currency (vs hold)."
    )
    note: str | None = None


class Alert(Model):
    alert_id: str
    run_id: str
    portfolio_id: str | None = None
    rule_id: str
    rule_version: int
    severity: AlertSeverity
    status: AlertStatus = AlertStatus.NEW
    as_of: AwareDatetime
    horizon: Horizon
    horizon_trading_days: int
    title: str
    summary: str
    triggering_event_ids: list[str] = Field(default_factory=list)
    affected_security_ids: list[str] = Field(default_factory=list)
    current_exposure: dict[str, float] = Field(default_factory=dict)
    metric_value: float
    threshold: float
    projected_loss: float | None = Field(default=None, description="Currency, positive = loss.")
    projected_loss_pct: float | None = None
    probability: float | None = Field(default=None, description="Simulated; uncalibrated in MVP.")
    confidence: Confidence
    limitations: list[str] = Field(default_factory=list)
    evidence: list[EvidenceItem] = Field(default_factory=list)
    alternatives: list[ActionOption] = Field(default_factory=list)
    expires_at: AwareDatetime | None = None
    superseded_by: str | None = None
    decision_boundary: str = DECISION_BOUNDARY


class AlertTransition(Model):
    alert_id: str
    from_status: AlertStatus
    to_status: AlertStatus
    at: AwareDatetime
    note: str | None = None


class ReplayFrame(Model):
    as_of: date
    portfolio_value: float = Field(description="Value of the held (no-change) portfolio.")
    metrics: RiskMetrics | None = None
    new_alert_ids: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(
        default_factory=list, description="Data failures at this step (RISK-05)."
    )


class ReplayResult(Model):
    run_id: str
    start: date
    end: date
    frames: list[ReplayFrame]
    alerts: list[Alert]
    model_version: str
    input_hash: str
    mode: str = "replay"

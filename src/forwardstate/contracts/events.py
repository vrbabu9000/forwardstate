"""Events, analyst observations and impact estimates (BRD p.5)."""

from __future__ import annotations

from enum import Enum

from pydantic import AwareDatetime, Field

from .common import Confidence, Model, Record


class EventClass(str, Enum):
    SCHEDULED = "scheduled"  # date known, outcome not (earnings, FOMC)
    ANTICIPATED = "anticipated"  # timing/outcome uncertain (possible rate change, regulation)
    UNEXPECTED = "unexpected"  # breaking news, sudden shocks


class EventScope(str, Enum):
    FIRM = "firm"
    SECTOR = "sector"
    MARKET = "market"


class EventStatus(str, Enum):
    UPCOMING = "upcoming"
    OCCURRED = "occurred"
    REVISED = "revised"
    CANCELLED = "cancelled"


class Direction(str, Enum):
    UP = "up"
    DOWN = "down"
    NEUTRAL = "neutral"
    UNKNOWN = "unknown"


class Event(Record):
    event_id: str
    event_class: EventClass
    subtype: str = Field(
        description="Sector taxonomy key, e.g. 'quarterly_results', 'fomc_meeting', "
        "'filing_8k', 'price_shock', 'rate_change'."
    )
    title: str
    status: EventStatus
    scope: EventScope
    scheduled_at: AwareDatetime | None = None
    occurred_at: AwareDatetime | None = None
    published_at: AwareDatetime | None = None
    affected_security_ids: list[str] = Field(default_factory=list)
    source_ids: list[str] = Field(default_factory=list, description="Raw source references/URLs.")
    expected_outcome: str | None = None
    actual_outcome: str | None = None
    surprise: float | None = Field(
        default=None,
        description="Relative surprise as a decimal: (actual - expected) / |expected|; -0.03 = -3%.",
    )
    revision: int = 0
    canonical_event_id: str | None = Field(
        default=None, description="Set when this record duplicates another (EVT-04)."
    )


class AnalystAction(str, Enum):
    UPGRADE = "upgrade"
    DOWNGRADE = "downgrade"
    INITIATE = "initiate"
    MAINTAIN = "maintain"
    TARGET_CHANGE = "target_change"
    OTHER = "other"


class AnalystObservation(Record):
    """An analyst view: evidence, never observed fact (EVT-03)."""

    observation_id: str
    analyst_source: str = Field(description="Firm or source name.")
    security_id: str
    action: AnalystAction
    from_rating: str | None = None
    to_rating: str | None = None
    target_price: float | None = None
    prior_target_price: float | None = None
    horizon_months: int | None = None
    assumptions: str | None = None
    issued_at: AwareDatetime
    revised_from: str | None = None
    confidence: float | None = None


class ImpactEstimate(Model):
    """Historical (realized) or forward (estimated) impact of an event on one security (EVT-05)."""

    event_id: str
    security_id: str
    realized: bool = Field(description="True = measured after the fact; False = forward estimate.")
    window_pre_days: int
    window_post_days: int
    direction: Direction
    abnormal_return: float | None = Field(
        default=None, description="Benchmark-adjusted cumulative abnormal return (CAR), decimal."
    )
    event_day_return: float | None = None
    post_event_drift: float | None = None
    t_stat: float | None = None
    expected_return_impact: float | None = None
    probability: float | None = Field(default=None, description="Only if calibrated; else None.")
    duration_days: int | None = None
    uncertainty: float | None = Field(default=None, description="Std. dev. of the estimate.")
    benchmark_id: str | None = None
    method: str
    sample_size: int = 0
    confidence: Confidence
    as_of: AwareDatetime
    evidence_ids: list[str] = Field(default_factory=list)
    note: str | None = Field(default=None, description="Association, not proven causation.")

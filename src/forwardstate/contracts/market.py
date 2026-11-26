"""Securities, prices, corporate actions, fundamentals and macro observations."""

from __future__ import annotations

from datetime import date
from enum import Enum

from pydantic import AwareDatetime, Field

from .common import Model, Record


class SecurityRole(str, Enum):
    FOCAL = "focal"
    PEER = "peer"
    BENCHMARK = "benchmark"  # analytical input, not investable (e.g. SPY, XLF)
    DEFENSIVE = "defensive"  # CASH


class Security(Model):
    security_id: str = Field(description="Stable id. MVP uses the ticker, e.g. 'JPM', 'CASH'.")
    ticker: str
    name: str
    sector: str
    currency: str = "USD"
    role: SecurityRole
    investable: bool = True


class PriceBar(Record):
    """One daily bar. Raw close is stored as fetched; adjustment is computed as-of (D007)."""

    security_id: str
    trading_date: date
    open: float | None = None
    high: float | None = None
    low: float | None = None
    raw_close: float
    adj_close: float | None = Field(
        default=None, description="Close adjusted for splits+dividends known as of the query."
    )
    volume: float | None = None
    currency: str = "USD"
    corporate_action_version: str | None = None


class CorporateActionKind(str, Enum):
    SPLIT = "split"
    DIVIDEND = "dividend"


class CorporateAction(Record):
    security_id: str
    ex_date: date
    kind: CorporateActionKind
    value: float = Field(description="Split ratio (e.g. 2.0) or cash dividend per share.")


class Observation(Record):
    """A fundamental or macro data point (DATA-02, DATA-03)."""

    metric_id: str = Field(description="e.g. 'DFF', 'DGS10', 'DGS2', 'eps_actual', 'eps_estimate'.")
    security_id: str | None = None  # set for company fundamentals
    economy: str | None = None  # e.g. 'US' for macro
    period_end: date
    value: float
    unit: str = Field(description="e.g. 'percent', 'usd_per_share', 'usd'.")
    release_at: AwareDatetime | None = None
    vintage: str | None = None


class SourceHealth(str, Enum):
    FRESH = "fresh"
    STALE = "stale"
    MISSING = "missing"
    ERROR = "error"
    DISABLED = "disabled"  # e.g. EDGAR without a User-Agent


class SourceStatus(Model):
    """Freshness of one source (NFR-02, AC-07 freshness states)."""

    source_id: str
    name: str
    health: SourceHealth
    last_fetched_at: AwareDatetime | None = None
    latest_record_date: date | None = None
    record_count: int = 0
    message: str | None = None

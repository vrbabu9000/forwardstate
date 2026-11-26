"""Shared enums, base record and helpers for every contract."""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from enum import Enum
from typing import Any

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

CONTRACT_VERSION = "1.0.0"

DECISION_BOUNDARY = (
    "ForwardState is decision support only. It does not trade, route orders or move money. "
    "You decide whether and how to act."
)


class Model(BaseModel):
    """Base for all contracts: strict field names, JSON-friendly."""

    model_config = ConfigDict(
        extra="forbid",
        populate_by_name=True,
        use_enum_values=False,
        # Fields with defaults are always present in responses; mark them required in the
        # serialization schema so the generated TypeScript types are not needlessly optional.
        json_schema_serialization_defaults_required=True,
    )


class DataOrigin(str, Enum):
    """Where a record came from. Always shown in the UI."""

    REAL = "real"  # fetched from a real source (Yahoo, FRED, EDGAR, Fed calendar)
    DERIVED = "derived"  # computed by ForwardState from real data (e.g. price-shock events)
    SYNTHETIC = "synthetic"  # generated; tests and offline demo only


class Confidence(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    UNAVAILABLE = "unavailable"  # not enough data: show this, never invent a number


class Horizon(str, Enum):
    SHORT = "short"  # default 20 trading days
    MEDIUM = "medium"  # default 126 trading days (~6 months)
    LONG = "long"  # default 504 trading days (~2 years)


DEFAULT_HORIZON_DAYS: dict[Horizon, int] = {
    Horizon.SHORT: 20,
    Horizon.MEDIUM: 126,
    Horizon.LONG: 504,
}


class DataMode(str, Enum):
    REPLAY = "replay"  # historical replay / simulation (the only MVP mode)
    LIVE = "live"  # Phase 3


class Record(Model):
    """Base for every time-sensitive record (BRD p.10 point-in-time rules).

    A run as of time T may use a record only if ``available_at <= T``.
    """

    source_id: str = Field(description="Source adapter id, e.g. 'yahoo', 'fred', 'edgar'.")
    origin: DataOrigin = DataOrigin.REAL
    available_at: AwareDatetime = Field(description="When this record became knowable (UTC).")
    availability_inferred: bool = Field(
        default=False, description="True when available_at was inferred by a D007 rule."
    )
    ingested_at: AwareDatetime | None = None


def _default(o: Any) -> Any:
    if isinstance(o, BaseModel):
        return o.model_dump(mode="json")
    if isinstance(o, (datetime, date)):
        return o.isoformat()
    if isinstance(o, Enum):
        return o.value
    if isinstance(o, (set, frozenset)):
        return sorted(o)
    if hasattr(o, "tolist"):  # numpy arrays / scalars
        return o.tolist()
    raise TypeError(f"Cannot hash object of type {type(o).__name__}")


def stable_hash(obj: Any) -> str:
    """Deterministic sha256 of any JSON-able object (pydantic models, dicts, lists, dates).

    Used for config hashes, input hashes and reproducibility checks (NFR-01, AC-06).
    """
    payload = json.dumps(obj, default=_default, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()

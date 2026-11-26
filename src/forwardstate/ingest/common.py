"""Shared helpers for source adapters: retries with backoff, a raw-download cache, results."""

from __future__ import annotations

import logging
import random
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, TypeVar

import pandas as pd

from forwardstate.contracts import (
    AnalystObservation,
    CorporateAction,
    Event,
    Observation,
    PriceBar,
)

log = logging.getLogger("forwardstate.ingest")

T = TypeVar("T")
DEFAULT_CACHE_DIR = Path("data/cache")


class EmptyResult(RuntimeError):
    """A source answered but returned nothing usable (often a soft rate limit)."""


def retry(fn: Callable[[], T], *, what: str, attempts: int = 4, base_delay: float = 2.0,
          is_empty: Callable[[T], bool] | None = None,
          sleep: Callable[[float], None] = time.sleep) -> T:
    """Call ``fn`` with exponential backoff. ``is_empty`` results are retried like errors."""
    last: Exception | None = None
    for i in range(attempts):
        try:
            out = fn()
            if is_empty is not None and is_empty(out):
                raise EmptyResult(f"{what}: empty result")
            return out
        except Exception as exc:  # noqa: BLE001 - every source error is retried, then reported
            last = exc
            if i == attempts - 1:
                break
            delay = base_delay * (2**i) * (1 + 0.25 * random.random())
            if "rate" in str(exc).lower() or "429" in str(exc):
                delay *= 3
            log.warning("%s failed (%s); retry %d/%d in %.1fs", what, exc, i + 1,
                        attempts - 1, delay)
            sleep(delay)
    assert last is not None
    raise last


class RawCache:
    """Raw downloads under ``data/cache/<source>/``. Entries younger than ``ttl`` are reused."""

    def __init__(self, root: Path | str = DEFAULT_CACHE_DIR, ttl: timedelta = timedelta(hours=12)):
        self.root = Path(root)
        self.ttl = ttl

    def path(self, source: str, name: str) -> Path:
        p = self.root / source / name
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    def fresh(self, p: Path) -> bool:
        return p.exists() and (time.time() - p.stat().st_mtime) < self.ttl.total_seconds()

    def text(self, source: str, name: str, fetch: Callable[[], str]) -> str:
        p = self.path(source, name)
        if self.fresh(p):
            return p.read_text()
        txt = fetch()
        p.write_text(txt)
        return txt

    def frame(self, source: str, name: str, fetch: Callable[[], pd.DataFrame | None]
              ) -> pd.DataFrame | None:
        p = self.path(source, name + ".parquet")
        if self.fresh(p):
            return pd.read_parquet(p)
        df = fetch()
        if df is not None:
            df.to_parquet(p)
        return df


@dataclass
class SourceResult:
    """What one adapter produced in one run."""

    source_id: str
    bars: list[PriceBar] = field(default_factory=list)
    actions: list[CorporateAction] = field(default_factory=list)
    observations: list[Observation] = field(default_factory=list)
    events: list[Event] = field(default_factory=list)
    analyst: list[AnalystObservation] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)
    disabled: str | None = None  # reason, when the source was skipped on purpose

    def total(self) -> int:
        return (len(self.bars) + len(self.actions) + len(self.observations) + len(self.events)
                + len(self.analyst))

    def latest_date(self) -> date | None:
        ds: list[date] = [b.trading_date for b in self.bars]
        ds += [o.period_end for o in self.observations]
        ds += [(e.occurred_at or e.available_at).date() for e in self.events
               if (e.occurred_at or e.available_at) <= datetime.now(tz=e.available_at.tzinfo)]
        return max(ds) if ds else None

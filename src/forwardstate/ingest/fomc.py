"""FOMC meeting events from ``configs/fomc_dates.yaml`` plus real outcomes from FRED.

Scheduled meetings: revision 0 UPCOMING (available 60 days before, inferred) and, once the
statement time has passed, revision 1 OCCURRED at 14:00 New York. ``actual_outcome`` is the
change in the FRED target upper bound (DFEDTARU) across the meeting, e.g. "+25 bps" or
"hold". If DFEDTARU is not available the outcome is left empty, never guessed.

Unscheduled meetings (e.g. March 2020) were not known in advance, so they get only an
OCCURRED revision and class UNEXPECTED. No UPCOMING record, so no look-ahead.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path

import yaml

from forwardstate.contracts import (
    DataOrigin,
    Event,
    EventClass,
    EventScope,
    EventStatus,
    Observation,
)
from forwardstate.pit import et

from .common import SourceResult

SRC = "fomc"
BANKS = ["JPM", "BAC", "C", "MS", "GS"]
CAL_URL = "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"


def default_config_path() -> Path:
    for base in (Path.cwd(), Path(__file__).resolve().parents[3]):
        p = base / "configs" / "fomc_dates.yaml"
        if p.exists():
            return p
    return Path("configs/fomc_dates.yaml")


def load_fomc_config(path: Path | None = None) -> tuple[list[date], list[dict]]:
    cfg = yaml.safe_load((path or default_config_path()).read_text())
    scheduled = sorted(date.fromisoformat(str(d)) for ds in cfg["scheduled"].values() for d in ds)
    unscheduled = [dict(u, date=date.fromisoformat(str(u["date"])))
                   for u in cfg.get("unscheduled", [])]
    return scheduled, unscheduled


def target_change_bps(d: date, upper: list[Observation]) -> int | None:
    """Change in the target upper bound from the last value before ``d`` to the first after."""
    pts = sorted((o.period_end, o.value) for o in upper)
    before = [v for pe, v in pts if pe < d]
    after = [v for pe, v in pts if pe > d]
    if not before or not after:
        return None
    return round((after[0] - before[-1]) * 100)


def outcome_text(bps: int | None) -> str | None:
    if bps is None:
        return None
    return "hold" if bps == 0 else f"{bps:+d} bps"


def build_fomc_events(upper_bound: list[Observation], now: datetime, start: date,
                      config: Path | None = None) -> SourceResult:
    res = SourceResult(SRC)
    scheduled, unscheduled = load_fomc_config(config)
    missing_outcome = []

    def base(d: date, cls: EventClass, title: str) -> dict:
        return {
            "source_id": SRC, "origin": DataOrigin.REAL, "event_id": f"fomc-{d.isoformat()}",
            "event_class": cls, "subtype": "fomc_meeting", "title": title,
            "scope": EventScope.MARKET, "affected_security_ids": list(BANKS),
            "source_ids": [CAL_URL, "fred:DFEDTARU"],
        }

    def occurred(b: dict, when: datetime, d: date, revision: int = 1) -> Event:
        bps = target_change_bps(d, upper_bound)
        if bps is None:
            missing_outcome.append(d.isoformat())
        return Event(**b, status=EventStatus.OCCURRED, revision=revision, occurred_at=when,
                     published_at=when, actual_outcome=outcome_text(bps),
                     surprise=None, available_at=when, availability_inferred=True)

    for d in scheduled:
        if d < start:
            continue
        when = et(d, 14, 0)
        b = base(d, EventClass.SCHEDULED, f"FOMC decision {d.isoformat()}")
        b["scheduled_at"] = when
        res.events.append(Event(**b, status=EventStatus.UPCOMING, revision=0,
                                available_at=when - timedelta(days=60),
                                availability_inferred=True))
        if when <= now:
            res.events.append(occurred(b, when, d))
    for u in unscheduled:
        d = u["date"]
        hh, mm = (int(x) for x in str(u.get("time_et", "14:00")).split(":"))
        when = et(d, hh, mm)
        if d < start or when > now:
            continue
        b = base(d, EventClass.UNEXPECTED, f"Unscheduled FOMC decision {d.isoformat()}")
        res.events.append(occurred(b, when, d, revision=0))
    res.details = {"scheduled": len([d for d in scheduled if d >= start]),
                   "unscheduled": len(unscheduled), "events": len(res.events),
                   "outcome_missing": missing_outcome}
    return res

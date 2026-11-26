"""Point-in-time helpers shared by every store implementation (D007). Owned by the integrator."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from .contracts import CorporateAction, CorporateActionKind

NY = ZoneInfo("America/New_York")
UTC = timezone.utc


def et(d: date, hh: int, mm: int = 0) -> datetime:
    """A wall-clock time in New York on date ``d``, returned in UTC."""
    return datetime.combine(d, time(hh, mm), tzinfo=NY).astimezone(UTC)


def bar_available_at(trading_date: date) -> datetime:
    """D007: a daily bar is knowable at 16:15 New York time on its trading date."""
    return et(trading_date, 16, 15)


def end_of_day_utc(d: date) -> datetime:
    """Convenience: 23:59 New York on ``d`` (conservative availability)."""
    return et(d, 23, 59)


def as_of_for_date(d: date) -> datetime:
    """The as-of instant used when a user picks a calendar date: after that day's close data."""
    return et(d, 23, 59)


def ensure_utc(ts: datetime) -> datetime:
    if ts.tzinfo is None:
        raise ValueError("as_of must be timezone-aware (UTC).")
    return ts.astimezone(UTC)


def adjust_closes(
    prices: pd.DataFrame, actions: Iterable[CorporateAction], as_of: datetime
) -> pd.Series:
    """Return split- and dividend-adjusted closes, using only actions available by ``as_of``.

    ``prices`` must have columns ``security_id, trading_date, raw_close`` and be sorted by
    (security_id, trading_date). Uses the standard CRSP-style backward adjustment:
    - split with ratio r on ex_date: earlier closes are divided by r;
    - cash dividend D on ex_date: earlier closes are multiplied by (1 - D / prior close).
    """
    as_of = ensure_utc(as_of)
    out = prices["raw_close"].astype(float).copy()
    # An action counts only once it is known AND its ex-date has passed by as_of; a dividend
    # announced for a future ex-date must not adjust history yet.
    as_of_day = as_of.astimezone(NY).date()
    acts = [a for a in actions if a.available_at <= as_of and a.ex_date <= as_of_day]
    if not acts or prices.empty:
        return out
    by_sec: dict[str, list[CorporateAction]] = {}
    for a in acts:
        by_sec.setdefault(a.security_id, []).append(a)
    td = pd.to_datetime(prices["trading_date"]).to_numpy()
    sids = prices["security_id"].to_numpy()
    raw_all = out.to_numpy()
    result = raw_all.copy()
    for sid, sec_acts in by_sec.items():
        pos = np.flatnonzero(sids == sid)  # rows are sorted by date within a security
        if pos.size == 0:
            continue
        dates = td[pos]
        raw = raw_all[pos]
        factor = np.ones(pos.size)
        for a in sorted(sec_acts, key=lambda a: a.ex_date):
            k = int(np.searchsorted(dates, np.datetime64(a.ex_date), side="left"))  # rows < ex_date
            if k == 0:
                continue
            if a.kind == CorporateActionKind.SPLIT and a.value > 0:
                factor[:k] /= a.value
            elif a.kind == CorporateActionKind.DIVIDEND:
                prior_close = raw[k - 1]
                if prior_close > 0:
                    factor[:k] *= 1 - a.value / prior_close
        result[pos] = raw * factor
    return pd.Series(result, index=out.index, name=out.name)


def trading_days_between(start: date, end: date) -> int:
    """Approximate count of weekdays between two dates (holidays ignored)."""
    if end <= start:
        return 0
    return int(pd.bdate_range(start + timedelta(days=1), end).size)

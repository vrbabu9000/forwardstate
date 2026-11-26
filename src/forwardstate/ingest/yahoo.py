"""Yahoo Finance adapter (yfinance): daily bars, splits/dividends, earnings, analyst actions.

Point-in-time rules (D007), all marked ``availability_inferred=True``:
- bar: trading date 16:15 New York;
- split / dividend: ex-date 09:30 New York (conservative; real announcements come earlier);
- earnings: UPCOMING revision 30 days before the Yahoo earnings timestamp, OCCURRED revision
  (actual, estimate, surprise) at the timestamp itself;
- analyst action: grade date (converted to New York) at 23:59 New York.

Yahoo's "Close" with ``auto_adjust=False`` is already split-adjusted, so the true raw close
is rebuilt by multiplying back every split that happened after the bar date.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import date, datetime, timedelta
from functools import partial

import numpy as np
import pandas as pd

from forwardstate.contracts import (
    AnalystAction,
    AnalystObservation,
    CorporateAction,
    CorporateActionKind,
    DataOrigin,
    Event,
    EventClass,
    EventScope,
    EventStatus,
    Observation,
    PriceBar,
)
from forwardstate.pit import NY, UTC, bar_available_at, end_of_day_utc, et

from .common import RawCache, SourceResult, log, retry

SRC = "yahoo"
ETFS = {"SPY", "XLF"}
REAL = DataOrigin.REAL


def _num(x: object) -> float | None:
    try:
        v = float(x)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return None if np.isnan(v) else v


# ---- bars and corporate actions ---------------------------------------------------------
def split_factors(splits: pd.Series) -> pd.Series:
    """For each row, the product of split ratios strictly *after* that row's date.

    ``splits`` is Yahoo's "Stock Splits" column (0 = no split, 2.0 = 2-for-1, 0.1 = 1-for-10).
    raw value = Yahoo split-adjusted value * factor.
    """
    s = splits.fillna(0.0).astype(float).where(lambda v: v > 0, 1.0)
    from_here = s[::-1].cumprod()[::-1]  # product over j >= i
    return from_here / s  # product over j > i


def map_history(ticker: str, hist: pd.DataFrame, start: date, fetched_at: datetime
                ) -> tuple[list[PriceBar], list[CorporateAction]]:
    """Map a ``Ticker.history(auto_adjust=False, actions=True)`` frame to contract records."""
    if hist is None or hist.empty:
        return [], []
    h = hist.sort_index()
    factor = split_factors(h["Stock Splits"]) if "Stock Splits" in h else pd.Series(1.0, h.index)
    idx = pd.DatetimeIndex(h.index)
    days = (idx.tz_convert(NY) if idx.tz is not None else idx).date
    bars: list[PriceBar] = []
    actions: list[CorporateAction] = []
    for i, d in enumerate(days):
        row = h.iloc[i]
        f = float(factor.iloc[i])
        close = _num(row.get("Close"))
        if d < start:
            continue
        if close is not None and bar_available_at(d) <= fetched_at:
            o, hi, lo, vol = (_num(row.get(c)) for c in ("Open", "High", "Low", "Volume"))
            bars.append(PriceBar(
                source_id=SRC, origin=REAL, available_at=bar_available_at(d),
                availability_inferred=True, security_id=ticker, trading_date=d,
                open=None if o is None else o * f, high=None if hi is None else hi * f,
                low=None if lo is None else lo * f, raw_close=close * f,
                volume=None if vol is None else vol / f,
            ))
        split = _num(row.get("Stock Splits")) or 0.0
        if split > 0:
            actions.append(CorporateAction(
                source_id=SRC, origin=REAL, available_at=et(d, 9, 30), availability_inferred=True,
                security_id=ticker, ex_date=d, kind=CorporateActionKind.SPLIT, value=split))
        div = _num(row.get("Dividends")) or 0.0
        if div > 0:
            actions.append(CorporateAction(
                source_id=SRC, origin=REAL, available_at=et(d, 9, 30), availability_inferred=True,
                security_id=ticker, ex_date=d, kind=CorporateActionKind.DIVIDEND,
                value=round(div * f, 6)))
    return bars, actions


# ---- earnings ----------------------------------------------------------------------------
def _quarter_end_before(d: date) -> date:
    return (pd.Timestamp(d) - pd.offsets.QuarterEnd(1)).date()


def map_earnings(ticker: str, df: pd.DataFrame, start: date, now: datetime
                 ) -> tuple[list[Event], list[Observation]]:
    """Map ``get_earnings_dates()`` to quarterly_results events and EPS observations."""
    if df is None or df.empty:
        return [], []
    events: list[Event] = []
    obs: list[Observation] = []
    seen: set[date] = set()
    for ts, row in df.sort_index().iterrows():
        t = pd.Timestamp(ts)
        t = t.tz_localize(NY) if t.tzinfo is None else t
        when = t.tz_convert(UTC).to_pydatetime()
        d = t.tz_convert(NY).date()
        if d < start or d in seen:
            continue
        seen.add(d)
        eid = f"earnings-{ticker}-{d.isoformat()}"
        base = {
            "source_id": SRC, "origin": REAL, "event_id": eid,
            "event_class": EventClass.SCHEDULED, "subtype": "quarterly_results",
            "title": f"{ticker} quarterly results", "scope": EventScope.FIRM,
            "scheduled_at": when, "affected_security_ids": [ticker],
            "source_ids": [f"yahoo:earnings_dates:{ticker}"],
        }
        events.append(Event(**base, status=EventStatus.UPCOMING, revision=0,
                            available_at=when - timedelta(days=30), availability_inferred=True))
        actual = _num(row.get("Reported EPS"))
        est = _num(row.get("EPS Estimate"))
        if actual is None or when > now:
            continue
        pct = _num(row.get("Surprise(%)"))
        if pct is None and est not in (None, 0.0):
            pct = (actual - est) / abs(est) * 100  # type: ignore[operator]
        outcome = f"EPS {actual:.2f}"
        if est is not None:
            outcome += f" vs estimate {est:.2f}"
        if pct is not None:
            outcome += f" ({pct:+.1f}%)"
        events.append(Event(
            **base, status=EventStatus.OCCURRED, revision=1, occurred_at=when, published_at=when,
            expected_outcome=None if est is None else f"EPS estimate {est:.2f}",
            actual_outcome=outcome, surprise=None if pct is None else round(pct / 100, 6),
            available_at=when, availability_inferred=True,
        ))
        pe = _quarter_end_before(d)
        common = {"source_id": SRC, "origin": REAL, "available_at": when,
                  "availability_inferred": True, "security_id": ticker, "period_end": pe,
                  "release_at": when}
        obs.append(Observation(**common, metric_id="eps_actual", value=actual,
                               unit="usd_per_share"))
        if est is not None:
            obs.append(Observation(**common, metric_id="eps_estimate", value=est,
                                   unit="usd_per_share"))
        if pct is not None:
            obs.append(Observation(**common, metric_id="eps_surprise_pct", value=round(pct, 4),
                                   unit="percent"))
    return events, obs


# ---- analyst actions ---------------------------------------------------------------------
_ACTIONS = {"up": AnalystAction.UPGRADE, "down": AnalystAction.DOWNGRADE,
            "init": AnalystAction.INITIATE, "main": AnalystAction.MAINTAIN,
            "reit": AnalystAction.MAINTAIN}


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def _str(x: object) -> str | None:
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return None
    s = str(x).strip()
    return s or None


def map_upgrades_downgrades(ticker: str, df: pd.DataFrame, start: date
                            ) -> list[AnalystObservation]:
    """Map ``Ticker.upgrades_downgrades`` (index GradeDate, assumed UTC when naive)."""
    if df is None or df.empty:
        return []
    out: list[AnalystObservation] = []
    used: set[str] = set()
    for ts, row in df.sort_index().iterrows():
        t = pd.Timestamp(ts)
        t = t.tz_localize(UTC) if t.tzinfo is None else t.tz_convert(UTC)
        d = t.tz_convert(NY).date()
        if d < start:
            continue
        firm = _str(row.get("Firm")) or "unknown"
        action = _ACTIONS.get((_str(row.get("Action")) or "").lower(), AnalystAction.OTHER)
        target = _num(row.get("currentPriceTarget")) or None  # 0 means "not given"
        prior = _num(row.get("priorPriceTarget")) or None
        pt_action = (_str(row.get("priceTargetAction")) or "").lower()
        if action == AnalystAction.MAINTAIN and pt_action in {"raises", "lowers"}:
            action = AnalystAction.TARGET_CHANGE
        oid = f"yahoo-{ticker}-{t.strftime('%Y%m%dT%H%M%S')}-{_slug(firm)}"
        n, base_id = 1, oid
        while oid in used:
            n += 1
            oid = f"{base_id}-{n}"
        used.add(oid)
        out.append(AnalystObservation(
            source_id=SRC, origin=REAL, available_at=end_of_day_utc(d),
            availability_inferred=True, observation_id=oid, analyst_source=firm,
            security_id=ticker, action=action, from_rating=_str(row.get("FromGrade")),
            to_rating=_str(row.get("ToGrade")), target_price=target, prior_target_price=prior,
            issued_at=t.to_pydatetime(),
        ))
    return out


# ---- fetch -------------------------------------------------------------------------------
def _default_ticker(symbol: str):  # pragma: no cover - thin wrapper over the network
    import yfinance as yf

    return yf.Ticker(symbol)


def _get_frame(cache: RawCache, name: str, fn: Callable[[], pd.DataFrame | None], what: str,
               kw: dict) -> pd.DataFrame | None:
    return cache.frame(SRC, name, lambda: retry(
        fn, what=what, is_empty=lambda x: x is None or x.empty, **kw))


def fetch_yahoo(tickers: list[str], start: date, cache: RawCache, now: datetime,
                ticker_factory: Callable[[str], object] = _default_ticker,
                sleep: Callable[[float], None] | None = None) -> SourceResult:
    """Fetch every ticker; a failure for one ticker or one dataset never stops the others."""
    res = SourceResult(SRC)
    kw = {} if sleep is None else {"sleep": sleep}
    for tk in tickers:
        info: dict[str, object] = {}
        yt = ticker_factory(tk)
        try:
            h = _get_frame(cache, f"{tk}_history_{start.isoformat()}",
                           partial(yt.history, start=start.isoformat(), auto_adjust=False,
                                   actions=True), f"yahoo history {tk}", kw)
            bars, acts = map_history(tk, h, start, now)
            res.bars += bars
            res.actions += acts
            info.update(bars=len(bars), actions=len(acts),
                        first=str(bars[0].trading_date) if bars else None,
                        last=str(bars[-1].trading_date) if bars else None)
        except Exception as exc:  # noqa: BLE001
            res.errors.append(f"{tk} history: {exc}")
            info["bars"] = 0

        if tk not in ETFS:  # ETFs have no earnings or analyst grades
            try:
                e = _get_frame(cache, f"{tk}_earnings", partial(yt.get_earnings_dates, limit=60),
                               f"yahoo earnings {tk}", kw)
                evs, obs = map_earnings(tk, e, start, now)
                res.events += evs
                res.observations += obs
                info.update(earnings_events=len(evs), eps_observations=len(obs))
            except Exception as exc:  # noqa: BLE001
                res.errors.append(f"{tk} earnings: {exc}")
            try:
                u = _get_frame(cache, f"{tk}_upgrades_downgrades",
                               partial(getattr, yt, "upgrades_downgrades"),
                               f"yahoo analyst {tk}", kw)
                an = map_upgrades_downgrades(tk, u, start)
                res.analyst += an
                info.update(analyst=len(an),
                            analyst_first=str(an[0].issued_at.date()) if an else None)
            except Exception as exc:  # noqa: BLE001
                res.errors.append(f"{tk} analyst: {exc}")
        res.details[tk] = info
        log.info("yahoo %s: %s", tk, info)
    return res

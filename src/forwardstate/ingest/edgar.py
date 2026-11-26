"""SEC EDGAR adapter: filing dates from the submissions JSON (8-K, 10-Q, 10-K).

The SEC requires a descriptive User-Agent. It is read ONLY from the environment variable
``FORWARDSTATE_SEC_USER_AGENT``; without it the source is skipped and reported DISABLED.
Requests are throttled to at most 10 per second (SEC fair-access policy).

``available_at`` is the filing's ``acceptanceDateTime``. The submissions JSON writes it with a
trailing "Z", but the clock is US Eastern (e.g. JPM's earnings 8-Ks show ~06:50, matching a
pre-market release), so it is read as New York time and converted to UTC.
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Callable
from datetime import date, datetime

import pandas as pd

from forwardstate.contracts import DataOrigin, Event, EventClass, EventScope, EventStatus
from forwardstate.pit import NY, UTC

from .common import RawCache, SourceResult, retry

SRC = "edgar"
ENV_UA = "FORWARDSTATE_SEC_USER_AGENT"
CIKS = {"JPM": "0000019617", "BAC": "0000070858", "C": "0000831001", "MS": "0000895421",
        "GS": "0000886982"}
BASE = "https://data.sec.gov/submissions/"
FORMS = {
    "8-K": ("filing_8k", EventClass.UNEXPECTED),
    "10-Q": ("filing_10q", EventClass.SCHEDULED),
    "10-K": ("filing_10k", EventClass.SCHEDULED),
}
DISABLED_MSG = (f"EDGAR disabled: set {ENV_UA} to a descriptive User-Agent with your own "
                "contact details (SEC policy) and re-run fetch.")


class Throttle:
    """At most ``rate`` calls per second."""

    def __init__(self, rate: float = 10.0, clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], None] = time.sleep) -> None:
        self.gap = 1.0 / rate
        self.clock, self.sleep = clock, sleep
        self.last = -1e9

    def wait(self) -> None:
        dt = self.clock() - self.last
        if dt < self.gap:
            self.sleep(self.gap - dt)
        self.last = self.clock()


def parse_acceptance(s: str) -> datetime:
    """'2024-10-11T06:47:31.000Z' or '20241011064731' (Eastern wall clock) -> UTC."""
    s = str(s).strip()
    t = pd.Timestamp(s.removesuffix("Z"))
    if t.tzinfo is not None:
        t = t.tz_localize(None)
    return t.tz_localize(NY).tz_convert(UTC).to_pydatetime()


def map_filings(ticker: str, cik: str, block: dict, start: date) -> list[Event]:
    """Map one columnar filings block (``filings.recent`` or an extra file) to events."""
    out: list[Event] = []
    n = len(block.get("accessionNumber", []))
    col = {k: block.get(k, [None] * n) for k in
           ("accessionNumber", "filingDate", "reportDate", "acceptanceDateTime", "form",
            "items", "primaryDocument")}
    for i in range(n):
        form = col["form"][i]
        if form not in FORMS or not col["acceptanceDateTime"][i]:
            continue
        fdate = date.fromisoformat(col["filingDate"][i])
        if fdate < start:
            continue
        subtype, cls = FORMS[form]
        acc = col["accessionNumber"][i]
        when = parse_acceptance(col["acceptanceDateTime"][i])
        items = col["items"][i] or None
        title = f"{ticker} {form}" + (f" (items {items})" if items else "")
        report = col["reportDate"][i] or None
        url = (f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/"
               f"{acc.replace('-', '')}/{acc}-index.htm")
        out.append(Event(
            source_id=SRC, origin=DataOrigin.REAL, event_id=f"edgar-{acc}", event_class=cls,
            subtype=subtype, title=title, status=EventStatus.OCCURRED, scope=EventScope.FIRM,
            occurred_at=when, published_at=when, affected_security_ids=[ticker],
            source_ids=[url], actual_outcome=f"report period {report}" if report else None,
            available_at=when, availability_inferred=False,
        ))
    return out


def _default_get(url: str, ua: str) -> str:  # pragma: no cover - network
    import requests

    r = requests.get(url, timeout=60, headers={"User-Agent": ua,
                                               "Accept-Encoding": "gzip, deflate"})
    r.raise_for_status()
    return r.text


def fetch_edgar(tickers: list[str], start: date, cache: RawCache,
                get: Callable[[str, str], str] = _default_get,
                env: dict[str, str] | None = None, throttle: Throttle | None = None,
                sleep: Callable[[float], None] | None = None) -> SourceResult:
    res = SourceResult(SRC)
    ua = (env if env is not None else os.environ).get(ENV_UA, "").strip()
    if not ua:
        res.disabled = DISABLED_MSG
        return res
    th = throttle or Throttle()
    kw = {} if sleep is None else {"sleep": sleep}

    def fetch_json(name: str) -> dict:
        def call() -> str:
            th.wait()
            return get(BASE + name, ua)
        return json.loads(cache.text(SRC, name, lambda: retry(call, what=f"edgar {name}", **kw)))

    for tk in tickers:
        cik = CIKS.get(tk)
        if cik is None:
            continue
        try:
            sub = fetch_json(f"CIK{cik}.json")
            filings = sub.get("filings", {})
            evs = map_filings(tk, cik, filings.get("recent", {}), start)
            for f in filings.get("files", []):
                if f.get("filingTo") and date.fromisoformat(f["filingTo"]) < start:
                    continue
                evs += map_filings(tk, cik, fetch_json(f["name"]), start)
            seen: set[str] = set()
            evs = [e for e in evs if not (e.event_id in seen or seen.add(e.event_id))]
            res.events += evs
            res.details[tk] = {"events": len(evs)}
        except Exception as exc:  # noqa: BLE001
            res.errors.append(f"{tk}: {exc}")
    return res

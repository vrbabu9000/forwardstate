"""``forwardstate fetch``: pull every real source into the DuckDB point-in-time store."""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import date, datetime, timedelta
from pathlib import Path

from forwardstate.pit import UTC
from forwardstate.storage import DEFAULT_DB_PATH, DuckDBStore, load_sector_securities

from .common import DEFAULT_CACHE_DIR, RawCache, SourceResult
from .edgar import fetch_edgar
from .fomc import build_fomc_events
from .fred import fetch_fred
from .yahoo import fetch_yahoo

ALL_SOURCES = ["yahoo", "fred", "fomc", "edgar"]
log = logging.getLogger("forwardstate.ingest")


def _write(store: DuckDBStore, r: SourceResult, now: datetime) -> dict[str, int]:
    return {
        "prices": store.upsert_prices(r.bars, now=now),
        "corporate_actions": store.upsert_corporate_actions(r.actions, now=now),
        "observations": store.upsert_observations(r.observations, now=now),
        "events": store.upsert_events(r.events, now=now),
        "analyst_observations": store.upsert_analyst_observations(r.analyst, now=now),
    }


def run_fetch(start: str = "2015-01-01", sources: str = "all", tickers: str | None = None, *,
              db_path: Path | str = DEFAULT_DB_PATH, cache_dir: Path | str = DEFAULT_CACHE_DIR,
              cache_ttl_hours: float = 12.0, now: datetime | None = None,
              adapters: dict[str, Callable[..., SourceResult]] | None = None,
              out: Callable[[str], None] = print) -> int:
    """Fetch, upsert and log each source. Returns 0 unless a requested source failed outright."""
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
    start_d = date.fromisoformat(start)
    now = now or datetime.now(UTC)
    wanted = ALL_SOURCES if sources in ("all", "", None) else [
        s.strip().lower() for s in sources.split(",") if s.strip()]
    unknown = [s for s in wanted if s not in ALL_SOURCES]
    if unknown:
        out(f"Unknown source(s): {', '.join(unknown)}. Choose from {', '.join(ALL_SOURCES)}.")
        return 2
    store = DuckDBStore(db_path)
    cache = RawCache(cache_dir, timedelta(hours=cache_ttl_hours))
    tks = ([t.strip().upper() for t in tickers.split(",") if t.strip()] if tickers else
           [s.security_id for s in load_sector_securities() if s.security_id != "CASH"])
    a = {"yahoo": lambda: fetch_yahoo(tks, start_d, cache, now),
         "fred": lambda: fetch_fred(start_d, cache),
         "fomc": lambda upper: build_fomc_events(upper, now=now, start=start_d),
         "edgar": lambda: fetch_edgar(tks, start_d, cache)}
    a.update(adapters or {})

    failed = False
    fred_result: SourceResult | None = None
    out(f"ForwardState fetch from {start_d} (tickers: {', '.join(tks)})")
    for src in [s for s in ALL_SOURCES if s in wanted]:
        started = datetime.now(UTC)
        try:
            if src == "fomc":
                if fred_result is not None:
                    upper = [o for o in fred_result.observations if o.metric_id == "DFEDTARU"]
                else:
                    upper = store.observations(["DFEDTARU"], now)
                r = a["fomc"](upper)
            else:
                r = a[src]()
            if src == "fred":
                fred_result = r
        except Exception as exc:  # noqa: BLE001 - one source must not stop the rest
            store.log_fetch(src, started, "error", 0, f"{type(exc).__name__}: {exc}")
            out(f"  {src:6s} ERROR {exc}")
            failed = True
            continue
        if r.disabled:
            store.log_fetch(src, started, "disabled", 0, r.disabled)
            out(f"  {src:6s} DISABLED: {r.disabled}")
            continue
        written = _write(store, r, now)
        fetched = r.total()
        status = "ok" if not r.errors else ("partial" if fetched else "error")
        msg = "; ".join(r.errors)[:2000] if r.errors else None
        store.log_fetch(src, started, status, fetched, msg, r.latest_date(),
                        {"written": written, **r.details})
        if status == "error":
            failed = True
        new = sum(written.values())
        out(f"  {src:6s} {status.upper():7s} fetched {fetched} records, {new} new versions "
            f"stored; latest {r.latest_date()}")
        for k, v in r.details.items():
            out(f"           {k}: {v}")
        for e in r.errors:
            out(f"           error: {e}")
    out(f"Store: {Path(db_path)}")
    return 1 if failed else 0

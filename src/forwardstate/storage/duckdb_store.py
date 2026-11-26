"""DuckDB point-in-time store (BRD layer 2, D007).

Same read semantics as ``forwardstate.testing.fixture_store.FixtureStore``; the difference is
that nothing is ever overwritten:

- Every table is append-only. A record is identified by a key (e.g. security + trading date).
- If a later write carries the same key but different content, a new *version* is appended
  with ``available_at = max(record.available_at, write time)``. The old version is kept.
- A read as of T uses, per key, the highest version whose ``available_at <= T``. So a
  restatement fetched today never changes what a query for an earlier date returns.

Connections are opened per operation so that a reader (the API) and a writer (``fetch``) in
different processes do not hold the DuckDB file lock for long. Parsed tables are cached in
memory and reloaded when the database file changes.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable, Iterable
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, TypeVar

import duckdb
import pandas as pd
import yaml

from forwardstate.contracts import (
    AnalystObservation,
    CorporateAction,
    Event,
    EventClass,
    Observation,
    PriceBar,
    Record,
    Security,
    SecurityRole,
    SourceHealth,
    SourceStatus,
)
from forwardstate.pit import NY, UTC, adjust_closes, ensure_utc

DEFAULT_DB_PATH = Path("data/store/forwardstate.duckdb")
PRICE_COLUMNS = ["security_id", "trading_date", "raw_close", "adj_close", "volume", "available_at",
                 "origin"]
STALE_AFTER = timedelta(days=3)

# Known sources, shown by source_status() even before their first fetch.
SOURCE_NAMES: dict[str, str] = {
    "yahoo": "Yahoo Finance (prices, corporate actions, earnings, analyst actions)",
    "fred": "FRED, St. Louis Fed (rates)",
    "fomc": "Federal Reserve FOMC calendar",
    "edgar": "SEC EDGAR (filing dates)",
}

R = TypeVar("R", bound=Record)

# Fields that never count as a change of content (they describe when we learned it).
_VOLATILE = {"ingested_at", "available_at", "availability_inferred"}

_JSON_TABLES: dict[str, type[Record]] = {
    "corporate_actions": CorporateAction,
    "observations": Observation,
    "events": Event,
    "analyst_observations": AnalystObservation,
}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS prices (
    rkey VARCHAR, version INTEGER, security_id VARCHAR, trading_date DATE,
    open DOUBLE, high DOUBLE, low DOUBLE, raw_close DOUBLE, volume DOUBLE,
    currency VARCHAR, available_at TIMESTAMPTZ, availability_inferred BOOLEAN,
    origin VARCHAR, source_id VARCHAR, ingested_at TIMESTAMPTZ, content_hash VARCHAR
);
CREATE TABLE IF NOT EXISTS corporate_actions (
    rkey VARCHAR, version INTEGER, security_id VARCHAR, available_at TIMESTAMPTZ,
    source_id VARCHAR, content_hash VARCHAR, payload VARCHAR
);
CREATE TABLE IF NOT EXISTS observations (
    rkey VARCHAR, version INTEGER, metric_id VARCHAR, security_id VARCHAR, period_end DATE,
    available_at TIMESTAMPTZ, source_id VARCHAR, content_hash VARCHAR, payload VARCHAR
);
CREATE TABLE IF NOT EXISTS events (
    rkey VARCHAR, version INTEGER, event_id VARCHAR, revision INTEGER,
    available_at TIMESTAMPTZ, source_id VARCHAR, content_hash VARCHAR, payload VARCHAR
);
CREATE TABLE IF NOT EXISTS analyst_observations (
    rkey VARCHAR, version INTEGER, security_id VARCHAR, available_at TIMESTAMPTZ,
    source_id VARCHAR, content_hash VARCHAR, payload VARCHAR
);
CREATE TABLE IF NOT EXISTS fetch_log (
    source_id VARCHAR, started_at TIMESTAMPTZ, finished_at TIMESTAMPTZ, status VARCHAR,
    rows INTEGER, message VARCHAR, latest_record_date DATE, details VARCHAR
);
"""


def _now() -> datetime:
    return datetime.now(UTC)


def _round_floats(o: Any) -> Any:
    if isinstance(o, float):
        return round(o, 6)
    if isinstance(o, dict):
        return {k: _round_floats(v) for k, v in o.items()}
    if isinstance(o, list):
        return [_round_floats(v) for v in o]
    return o


def content_hash(rec: Record) -> str:
    """Hash of a record's content, ignoring when it was learned and float noise below 1e-6."""
    d = rec.model_dump(mode="json", exclude=_VOLATILE)
    payload = json.dumps(_round_floats(d), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


def _key(*parts: Any) -> str:
    return "|".join("" if p is None else (p.value if hasattr(p, "value") else str(p)) for p in parts)


def _price_key(b: PriceBar) -> str:
    return _key(b.security_id, b.trading_date)


def _action_key(a: CorporateAction) -> str:
    return _key(a.security_id, a.ex_date, a.kind)


def _obs_key(o: Observation) -> str:
    return _key(o.metric_id, o.security_id, o.period_end, o.vintage)


def _event_key(e: Event) -> str:
    return _key(e.event_id, e.revision)


def _analyst_key(o: AnalystObservation) -> str:
    return o.observation_id


def _ts(x: Any) -> datetime:
    t = pd.Timestamp(x)
    t = t.tz_localize(UTC) if t.tzinfo is None else t.tz_convert(UTC)
    return t.to_pydatetime()


def _latest_versions(df: pd.DataFrame, as_of: datetime) -> pd.DataFrame:
    """Per rkey, the highest version with available_at <= as_of."""
    f = df[df["available_at"] <= pd.Timestamp(as_of)]
    if f.empty:
        return f
    return f.sort_values(["rkey", "version"]).drop_duplicates("rkey", keep="last")


def _find_config(rel: str) -> Path:
    for base in (Path.cwd(), Path(__file__).resolve().parents[3]):
        p = base / rel
        if p.exists():
            return p
    return Path(rel)


def load_sector_securities(path: Path | None = None) -> list[Security]:
    """Universe, benchmarks (not investable) and CASH from the sector YAML config."""
    p = path or _find_config("configs/sectors/financials.yaml")
    cfg = yaml.safe_load(p.read_text())
    sector = cfg.get("sector", "financials")
    ccy = cfg.get("currency", "USD")
    out: list[Security] = []
    for u in cfg.get("universe", []):
        out.append(Security(security_id=u["ticker"], ticker=u["ticker"], name=u["name"],
                            sector=sector, currency=ccy, role=SecurityRole(u["role"])))
    for b in cfg.get("benchmarks", []):
        out.append(Security(security_id=b["ticker"], ticker=b["ticker"], name=b["name"],
                            sector=sector, currency=ccy, role=SecurityRole.BENCHMARK,
                            investable=False))
    for d in cfg.get("defensive_assets", []):
        out.append(Security(security_id=d["ticker"], ticker=d["ticker"], name=d["name"],
                            sector=sector, currency=ccy, role=SecurityRole.DEFENSIVE))
    return out


class DuckDBStore:
    """Implements ``forwardstate.services.PointInTimeStore`` on a DuckDB file."""

    def __init__(self, path: Path | str = DEFAULT_DB_PATH,
                 securities: list[Security] | None = None,
                 sector_config: Path | None = None) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._securities = securities
        self._sector_config = sector_config
        self._cache: dict[str, Any] = {}
        self._sig: tuple | None = None
        with self._connect() as con:
            con.execute(_SCHEMA)

    # ---- connection & cache ------------------------------------------------------------
    def _connect(self, attempts: int = 20) -> duckdb.DuckDBPyConnection:
        last: Exception | None = None
        for i in range(attempts):
            try:
                con = duckdb.connect(str(self.path))
                con.execute("SET TimeZone='UTC'")
                return con
            except duckdb.IOException as exc:  # file locked by another process
                last = exc
                time.sleep(min(0.05 * (2**i), 2.0))
        raise RuntimeError(f"Could not open {self.path}: {last}")

    def _signature(self) -> tuple:
        sig = []
        for p in (self.path, self.path.with_name(self.path.name + ".wal")):
            try:
                st = p.stat()
                sig.append((st.st_mtime_ns, st.st_size))
            except FileNotFoundError:
                sig.append(None)
        return tuple(sig)

    def _cached(self, name: str, loader: Callable[[], Any]) -> Any:
        sig = self._signature()
        if sig != self._sig:
            self._cache.clear()
            self._sig = sig
        if name not in self._cache:
            self._cache[name] = loader()
        return self._cache[name]

    def _invalidate(self) -> None:
        self._cache.clear()
        self._sig = None

    def _query_df(self, sql: str, params: list | None = None) -> pd.DataFrame:
        with self._connect() as con:
            return con.execute(sql, params or []).df()

    def _price_versions(self) -> pd.DataFrame:
        def load() -> pd.DataFrame:
            f = self._query_df(
                "SELECT rkey, version, security_id, trading_date, raw_close, volume, "
                "available_at, origin FROM prices")
            f["trading_date"] = pd.to_datetime(f["trading_date"]).astype("datetime64[ns]")
            f["available_at"] = pd.to_datetime(f["available_at"], utc=True).astype(
                "datetime64[ns, UTC]")
            f["raw_close"] = f["raw_close"].astype(float)
            f["volume"] = f["volume"].astype(float)
            return f
        return self._cached("prices", load)

    def _json_versions(self, table: str) -> pd.DataFrame:
        model = _JSON_TABLES[table]

        def load() -> pd.DataFrame:
            f = self._query_df(f"SELECT rkey, version, available_at, payload FROM {table}")
            f["available_at"] = pd.to_datetime(f["available_at"], utc=True)
            f["record"] = [model.model_validate_json(p) for p in f["payload"]]
            return f.drop(columns=["payload"])
        return self._cached(table, load)

    def _records_as_of(self, table: str, as_of: datetime) -> list:
        f = _latest_versions(self._json_versions(table), as_of)
        return list(f.sort_values(["rkey"])["record"]) if len(f) else []

    # ---- reads -------------------------------------------------------------------------
    def securities(self, sector: str | None = None) -> list[Security]:
        if self._securities is None:
            self._securities = load_sector_securities(self._sector_config)
        return [s for s in self._securities if sector is None or s.sector == sector]

    def prices(self, security_ids: list[str], as_of: datetime, start: date | None = None,
               end: date | None = None) -> pd.DataFrame:
        as_of = ensure_utc(as_of)
        f = self._price_versions()
        f = f[f["security_id"].isin(security_ids)]
        f = _latest_versions(f, as_of)
        if start:
            f = f[f["trading_date"] >= pd.Timestamp(start)]
        if end:
            f = f[f["trading_date"] <= pd.Timestamp(end)]
        f = f.sort_values(["security_id", "trading_date"]).reset_index(drop=True)
        f = f.drop(columns=["rkey", "version"])
        f = f.assign(adj_close=adjust_closes(f, self.corporate_actions(security_ids, as_of),
                                             as_of))
        return f[PRICE_COLUMNS]

    def returns(self, security_ids: list[str], as_of: datetime, start: date | None = None,
                end: date | None = None) -> pd.DataFrame:
        p = self.prices(security_ids, as_of, start, end)
        wide = p.pivot(index="trading_date", columns="security_id", values="adj_close").sort_index()
        return wide.pct_change(fill_method=None).iloc[1:].reindex(
            columns=[s for s in security_ids if s in wide.columns])

    def corporate_actions(self, security_ids: list[str], as_of: datetime) -> list[CorporateAction]:
        as_of = ensure_utc(as_of)
        return [a for a in self._records_as_of("corporate_actions", as_of)
                if a.security_id in security_ids]

    def observations(self, metric_ids: list[str], as_of: datetime, security_id: str | None = None,
                     start: date | None = None) -> list[Observation]:
        as_of = ensure_utc(as_of)
        out = [
            o for o in self._records_as_of("observations", as_of)
            if o.metric_id in metric_ids
            and (security_id is None or o.security_id == security_id)
            and (start is None or o.period_end >= start)
        ]
        return sorted(out, key=lambda o: (o.metric_id, o.security_id or "", o.period_end))

    def events(self, as_of: datetime, security_ids: list[str] | None = None,
               event_classes: list[EventClass] | None = None, start: date | None = None,
               end: date | None = None) -> list[Event]:
        """Latest revision of each event_id that is available by ``as_of``."""
        as_of = ensure_utc(as_of)
        latest: dict[str, Event] = {}
        for e in self._records_as_of("events", as_of):
            cur = latest.get(e.event_id)
            if cur is None or e.revision > cur.revision:
                latest[e.event_id] = e
        out = []
        for e in latest.values():
            when = (e.occurred_at or e.scheduled_at or e.available_at).astimezone(NY).date()
            if security_ids and not set(security_ids) & set(e.affected_security_ids):
                continue
            if event_classes and e.event_class not in event_classes:
                continue
            if start and when < start:
                continue
            if end and when > end:
                continue
            out.append(e)
        return sorted(out, key=lambda e: (e.occurred_at or e.scheduled_at or e.available_at,
                                          e.event_id))

    def analyst_observations(self, as_of: datetime,
                             security_ids: list[str] | None = None) -> list[AnalystObservation]:
        as_of = ensure_utc(as_of)
        return sorted(
            (o for o in self._records_as_of("analyst_observations", as_of)
             if not security_ids or o.security_id in security_ids),
            key=lambda o: (o.issued_at, o.observation_id),
        )

    def latest_as_of(self) -> datetime:
        f = self._price_versions()
        if f.empty:
            raise LookupError("No price data in the store yet. Run `forwardstate fetch`.")
        return f["available_at"].max().to_pydatetime()

    def price_row_count(self) -> int:
        return len(self._price_versions())

    # ---- fetch log & source status -----------------------------------------------------
    def log_fetch(self, source_id: str, started_at: datetime, status: str, rows: int = 0,
                  message: str | None = None, latest_record_date: date | None = None,
                  details: dict | None = None, finished_at: datetime | None = None) -> None:
        """status: 'ok', 'partial', 'error' or 'disabled'."""
        with self._connect() as con:
            con.execute(
                "INSERT INTO fetch_log VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                [source_id, ensure_utc(started_at), ensure_utc(finished_at or _now()), status,
                 rows, message, latest_record_date, json.dumps(details or {}, default=str)],
            )
        self._invalidate()

    def fetch_log(self) -> pd.DataFrame:
        return self._query_df("SELECT * FROM fetch_log ORDER BY finished_at")

    def _source_counts(self) -> dict[str, tuple[int, date | None]]:
        sql = """
        SELECT source_id, count(*) AS n,
               max(CASE WHEN available_at <= current_timestamp THEN d END) AS latest FROM (
            SELECT source_id, available_at, trading_date AS d FROM prices
            UNION ALL SELECT source_id, available_at, CAST(available_at AS DATE)
                FROM corporate_actions
            UNION ALL SELECT source_id, available_at, period_end FROM observations
            UNION ALL SELECT source_id, available_at, CAST(available_at AS DATE) FROM events
            UNION ALL SELECT source_id, available_at, CAST(available_at AS DATE)
                FROM analyst_observations
        ) GROUP BY source_id
        """
        f = self._query_df(sql)
        return {r.source_id: (int(r.n), pd.Timestamp(r.latest).date() if pd.notna(r.latest)
                              else None) for r in f.itertuples()}

    def source_status(self, now: datetime | None = None) -> list[SourceStatus]:
        now = ensure_utc(now) if now else _now()
        log = self.fetch_log()
        counts = self._source_counts()
        ids = list(SOURCE_NAMES) + sorted(
            (set(log["source_id"]) | set(counts)) - set(SOURCE_NAMES))
        out: list[SourceStatus] = []
        for sid in ids:
            n, latest = counts.get(sid, (0, None))
            rows = log[log["source_id"] == sid]
            name = SOURCE_NAMES.get(sid, sid)
            if rows.empty:
                health = SourceHealth.MISSING if n == 0 else SourceHealth.STALE
                out.append(SourceStatus(source_id=sid, name=name, health=health, record_count=n,
                                        latest_record_date=latest,
                                        message="Never fetched. Run `forwardstate fetch`."))
                continue
            last = rows.iloc[-1]
            fetched = _ts(last["finished_at"])
            ok = rows[rows["status"].isin(["ok", "partial"])]
            status = last["status"]
            if status == "disabled":
                health = SourceHealth.DISABLED
            elif status == "error":
                health = SourceHealth.ERROR
            elif n == 0:
                health = SourceHealth.MISSING
            else:
                health = SourceHealth.STALE if now - fetched > STALE_AFTER else SourceHealth.FRESH
            last_ok = _ts(ok.iloc[-1]["finished_at"]) if len(ok) else None
            out.append(SourceStatus(
                source_id=sid, name=name, health=health,
                last_fetched_at=last_ok if health == SourceHealth.ERROR and last_ok else fetched,
                latest_record_date=latest, record_count=n,
                message=None if pd.isna(last["message"]) else str(last["message"]),
            ))
        return out

    # ---- writes ------------------------------------------------------------------------
    def _append(self, table: str, records: Iterable[R], keyf: Callable[[R], str],
                row: Callable[[str, int, R, str], list], now: datetime | None = None) -> int:
        """Append new keys and changed versions. Returns the number of rows written."""
        now = ensure_utc(now) if now else _now()
        recs = list(records)
        if not recs:
            return 0
        with self._connect() as con:
            cur = con.execute(
                f"SELECT rkey, max(version) AS v, arg_max(content_hash, version) AS h "
                f"FROM {table} GROUP BY rkey").fetchall()
            latest = {k: (v, h) for k, v, h in cur}
            rows: list[list] = []
            for rec in recs:
                k = keyf(rec)
                h = content_hash(rec)
                prev = latest.get(k)
                if prev is not None and prev[1] == h:
                    continue
                if prev is None:
                    version = 0
                else:
                    # Restatement: keep the old version; the new one is knowable from now on.
                    version = prev[0] + 1
                    avail = max(rec.available_at.astimezone(UTC), now)
                    rec = rec.model_copy(update={"available_at": avail,
                                                 "availability_inferred": False})
                if rec.ingested_at is None:
                    rec = rec.model_copy(update={"ingested_at": now})
                latest[k] = (version, h)
                rows.append(row(k, version, rec, h))
            if rows:
                cols = [c[0] for c in con.execute(f"DESCRIBE {table}").fetchall()]
                batch = pd.DataFrame(rows, columns=cols)
                for c in ("available_at", "ingested_at"):
                    if c in batch:
                        batch[c] = pd.to_datetime(batch[c], utc=True)
                for c in ("trading_date", "period_end"):
                    if c in batch:
                        batch[c] = pd.to_datetime(batch[c])
                con.register("batch", batch)
                con.execute(f"INSERT INTO {table} SELECT * FROM batch")
        self._invalidate()
        return len(rows)

    def upsert_prices(self, bars: list[PriceBar], now: datetime | None = None) -> int:
        def row(k: str, v: int, b: PriceBar, h: str) -> list:
            return [k, v, b.security_id, b.trading_date, b.open, b.high, b.low, b.raw_close,
                    b.volume, b.currency, b.available_at, b.availability_inferred, b.origin.value,
                    b.source_id, b.ingested_at, h]
        return self._append("prices", bars, _price_key, row, now)

    def upsert_corporate_actions(self, actions: list[CorporateAction],
                                 now: datetime | None = None) -> int:
        def row(k: str, v: int, a: CorporateAction, h: str) -> list:
            return [k, v, a.security_id, a.available_at, a.source_id, h, a.model_dump_json()]
        return self._append("corporate_actions", actions, _action_key, row, now)

    def upsert_observations(self, obs: list[Observation], now: datetime | None = None) -> int:
        def row(k: str, v: int, o: Observation, h: str) -> list:
            return [k, v, o.metric_id, o.security_id, o.period_end, o.available_at, o.source_id,
                    h, o.model_dump_json()]
        return self._append("observations", obs, _obs_key, row, now)

    def upsert_events(self, events: list[Event], now: datetime | None = None) -> int:
        def row(k: str, v: int, e: Event, h: str) -> list:
            return [k, v, e.event_id, e.revision, e.available_at, e.source_id, h,
                    e.model_dump_json()]
        return self._append("events", events, _event_key, row, now)

    def upsert_analyst_observations(self, obs: list[AnalystObservation],
                                    now: datetime | None = None) -> int:
        def row(k: str, v: int, o: AnalystObservation, h: str) -> list:
            return [k, v, o.security_id, o.available_at, o.source_id, h, o.model_dump_json()]
        return self._append("analyst_observations", obs, _analyst_key, row, now)


def open_store(path: Path | str = DEFAULT_DB_PATH) -> DuckDBStore | None:
    """The real store, or None when no price data has been fetched yet."""
    p = Path(path)
    if not p.exists():
        return None
    store = DuckDBStore(p)
    return store if store.price_row_count() > 0 else None

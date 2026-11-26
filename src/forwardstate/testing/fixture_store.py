"""In-memory PointInTimeStore over any record lists (synthetic by default). Owned by the integrator.

This is also the reference behaviour for the real DuckDB store in ``forwardstate.storage``:
the same inputs must give the same outputs.
"""

from __future__ import annotations

from datetime import date, datetime

import pandas as pd

from forwardstate.contracts import (
    AnalystObservation,
    CorporateAction,
    Event,
    EventClass,
    Observation,
    PriceBar,
    Security,
    SourceHealth,
    SourceStatus,
)
from forwardstate.pit import NY, adjust_closes, ensure_utc

from .synthetic import SyntheticDataset, build_synthetic_dataset

PRICE_COLUMNS = ["security_id", "trading_date", "raw_close", "adj_close", "volume", "available_at", "origin"]


class FixtureStore:
    """Implements ``forwardstate.services.PointInTimeStore`` in memory."""

    def __init__(self, dataset: SyntheticDataset | None = None) -> None:
        ds = dataset or build_synthetic_dataset()
        self._securities: list[Security] = list(ds.securities)
        self._bars: list[PriceBar] = []
        self._actions: list[CorporateAction] = []
        self._obs: list[Observation] = []
        self._events: list[Event] = []
        self._analyst: list[AnalystObservation] = []
        self._frame: pd.DataFrame | None = None
        self.upsert_prices(ds.bars)
        self.upsert_corporate_actions(ds.actions)
        self.upsert_observations(ds.observations)
        self.upsert_events(ds.events)
        self.upsert_analyst_observations(ds.analyst)

    # ---- reads -------------------------------------------------------------------------
    def securities(self, sector: str | None = None) -> list[Security]:
        return [s for s in self._securities if sector is None or s.sector == sector]

    def _price_frame(self) -> pd.DataFrame:
        if self._frame is None:
            rows = [
                (b.security_id, pd.Timestamp(b.trading_date), b.raw_close, b.volume,
                 pd.Timestamp(b.available_at), b.origin.value)
                for b in self._bars
            ]
            f = pd.DataFrame(rows, columns=["security_id", "trading_date", "raw_close", "volume",
                                             "available_at", "origin"])
            self._frame = f.sort_values(["security_id", "trading_date"]).reset_index(drop=True)
        return self._frame

    def prices(self, security_ids: list[str], as_of: datetime, start: date | None = None,
               end: date | None = None) -> pd.DataFrame:
        as_of = ensure_utc(as_of)
        f = self._price_frame()
        f = f[f["security_id"].isin(security_ids) & (f["available_at"] <= pd.Timestamp(as_of))]
        if start:
            f = f[f["trading_date"] >= pd.Timestamp(start)]
        if end:
            f = f[f["trading_date"] <= pd.Timestamp(end)]
        f = f.sort_values(["security_id", "trading_date"]).reset_index(drop=True)
        f = f.assign(adj_close=adjust_closes(f, self.corporate_actions(security_ids, as_of), as_of))
        return f[PRICE_COLUMNS]

    def returns(self, security_ids: list[str], as_of: datetime, start: date | None = None,
                end: date | None = None) -> pd.DataFrame:
        p = self.prices(security_ids, as_of, start, end)
        wide = p.pivot(index="trading_date", columns="security_id", values="adj_close").sort_index()
        return wide.pct_change(fill_method=None).iloc[1:].reindex(columns=[s for s in security_ids if s in wide.columns])

    def corporate_actions(self, security_ids: list[str], as_of: datetime) -> list[CorporateAction]:
        as_of = ensure_utc(as_of)
        return [a for a in self._actions if a.security_id in security_ids and a.available_at <= as_of]

    def observations(self, metric_ids: list[str], as_of: datetime, security_id: str | None = None,
                     start: date | None = None) -> list[Observation]:
        as_of = ensure_utc(as_of)
        return [
            o for o in self._obs
            if o.metric_id in metric_ids and o.available_at <= as_of
            and (security_id is None or o.security_id == security_id)
            and (start is None or o.period_end >= start)
        ]

    def events(self, as_of: datetime, security_ids: list[str] | None = None,
               event_classes: list[EventClass] | None = None, start: date | None = None,
               end: date | None = None) -> list[Event]:
        """Latest revision of each event_id that is available by ``as_of``."""
        as_of = ensure_utc(as_of)
        latest: dict[str, Event] = {}
        for e in self._events:
            if e.available_at > as_of:
                continue
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
        return sorted(out, key=lambda e: e.occurred_at or e.scheduled_at or e.available_at)

    def analyst_observations(self, as_of: datetime,
                             security_ids: list[str] | None = None) -> list[AnalystObservation]:
        as_of = ensure_utc(as_of)
        return sorted(
            (o for o in self._analyst
             if o.available_at <= as_of and (not security_ids or o.security_id in security_ids)),
            key=lambda o: o.issued_at,
        )

    def latest_as_of(self) -> datetime:
        return self._price_frame()["available_at"].max().to_pydatetime()

    def source_status(self) -> list[SourceStatus]:
        f = self._price_frame()
        return [SourceStatus(
            source_id="synthetic", name="Synthetic fixture (not real data)", health=SourceHealth.FRESH,
            latest_record_date=f["trading_date"].max().date() if len(f) else None,
            record_count=len(self._bars) + len(self._obs) + len(self._events) + len(self._analyst),
            message="Labelled synthetic data for tests and offline demo.",
        )]

    # ---- writes ------------------------------------------------------------------------
    def upsert_prices(self, bars: list[PriceBar]) -> int:
        keyed = {(b.security_id, b.trading_date): b for b in self._bars}
        keyed.update({(b.security_id, b.trading_date): b for b in bars})
        self._bars = list(keyed.values())
        self._frame = None
        return len(bars)

    def upsert_corporate_actions(self, actions: list[CorporateAction]) -> int:
        keyed = {(a.security_id, a.ex_date, a.kind): a for a in self._actions}
        keyed.update({(a.security_id, a.ex_date, a.kind): a for a in actions})
        self._actions = list(keyed.values())
        return len(actions)

    def upsert_observations(self, obs: list[Observation]) -> int:
        keyed = {(o.metric_id, o.security_id, o.period_end, o.vintage): o for o in self._obs}
        keyed.update({(o.metric_id, o.security_id, o.period_end, o.vintage): o for o in obs})
        self._obs = list(keyed.values())
        return len(obs)

    def upsert_events(self, events: list[Event]) -> int:
        keyed = {(e.event_id, e.revision): e for e in self._events}
        keyed.update({(e.event_id, e.revision): e for e in events})
        self._events = list(keyed.values())
        return len(events)

    def upsert_analyst_observations(self, obs: list[AnalystObservation]) -> int:
        keyed = {o.observation_id: o for o in self._analyst}
        keyed.update({o.observation_id: o for o in obs})
        self._analyst = list(keyed.values())
        return len(obs)

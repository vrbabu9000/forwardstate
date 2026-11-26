"""EventEngine: stored + derived events and impact estimates (implements ``EventService``).

Point-in-time: every store read uses the caller's ``as_of``. A realized impact exists only
when the whole post-event window (+20 trading days) has a bar available by ``as_of``.
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import date, datetime

import numpy as np
import pandas as pd

from forwardstate.contracts import (
    Confidence,
    DataOrigin,
    Direction,
    Event,
    EventClass,
    EventScope,
    EventStatus,
    ImpactEstimate,
)
from forwardstate.industries import get_sector
from forwardstate.pit import NY, bar_available_at, ensure_utc, et

from .study import (
    CAR_END,
    CAR_START,
    DRIFT_END,
    MEDIUM_EST_OBS,
    T_CRIT,
    StudyResult,
    day_index,
    event_day,
    event_time,
    market_model_study,
    rolling_abnormal,
)

# ---- shock rule (derived price-shock events) ----------------------------------------------
SHOCK_WINDOW = 60  # rolling market-model window, trading days before the shock day
SHOCK_Z = 3.0  # |abnormal| must exceed this many residual standard deviations ...
SHOCK_MIN_ABS = 0.03  # ... AND be larger than 3% in absolute size
SECTOR_MIN_BANKS = 2  # this many banks shocking the same day -> one SECTOR event

# ---- forward-estimate confidence by sample size --------------------------------------------
FWD_HIGH, FWD_MEDIUM, FWD_LOW = 12, 6, 2

DERIVED_SOURCE = "forwardstate"
NOTE = "Association, not proven causation."
STUDY_METHOD = (
    "market-model event study vs {bm}: estimation [-250,-11], CAR [-1,+1], drift [+2,+20]"
)
FORWARD_METHOD = "mean historical CAR, same subtype, scope and security (market model vs {bm})"
_SCOPE_RANK = {EventScope.FIRM: 0, EventScope.SECTOR: 1, EventScope.MARKET: 2}


@dataclass
class _Context:
    """Everything one as-of needs, computed once and cached."""

    as_of: datetime
    returns: pd.DataFrame
    dates: pd.DatetimeIndex
    stored: list[Event]
    events: list[Event]
    by_id: dict[str, Event]
    studies: dict[tuple[str, str], StudyResult | None] = field(default_factory=dict)


class EventEngine:
    """Implements ``forwardstate.services.EventService`` for one sector."""

    def __init__(self, store, sector: str = "financials", cache_size: int = 16) -> None:
        self.store = store
        self.sector = get_sector(sector)
        self.banks: list[str] = [s.security_id for s in self.sector.universe()]
        bms = [s.security_id for s in self.sector.benchmarks()]
        self.market_id = "SPY" if "SPY" in bms else bms[0]
        self.sector_bm_id = "XLF" if "XLF" in bms else bms[-1]
        self._cache: OrderedDict[tuple[datetime, datetime], _Context] = OrderedDict()
        self._cache_size = cache_size

    def clear_cache(self) -> None:
        self._cache.clear()

    # ---- EventService ------------------------------------------------------------------
    def list_events(
        self,
        as_of: datetime,
        security_ids: list[str] | None = None,
        event_classes: list[EventClass] | None = None,
        start: date | None = None,
        end: date | None = None,
    ) -> list[Event]:
        ctx = self._context(as_of)
        out = []
        for e in ctx.events:
            when = event_time(e).astimezone(NY).date()
            if security_ids and not set(security_ids) & set(e.affected_security_ids):
                continue
            if event_classes and e.event_class not in event_classes:
                continue
            if start and when < start:
                continue
            if end and when > end:
                continue
            out.append(e)
        return out

    def impact_estimates(
        self, as_of: datetime, event_id: str | None = None, security_id: str | None = None
    ) -> list[ImpactEstimate]:
        ctx = self._context(as_of)
        pairs: list[tuple[Event, str, float]] = []
        if event_id is not None:
            ev = ctx.by_id.get(event_id)
            if ev is None:
                return []
            ids = [security_id] if security_id else list(self.banks)
            weights = self.sector.exposure(ev, ids, ctx.returns) if _takes_returns(self.sector) \
                else self.sector.exposure(ev, ids)
            pairs = [(ev, sid, float(weights.get(sid, 0.0))) for sid in ids]
        else:
            for ev in ctx.events:
                for sid in ev.affected_security_ids:
                    if security_id and sid != security_id:
                        continue
                    pairs.append((ev, sid, 1.0))
        return [self._estimate(ctx, ev, sid, w) for ev, sid, w in pairs]

    # ---- helpers used by the forecast layer ----------------------------------------------
    def realized_study(self, as_of: datetime, event_id: str, security_id: str):
        """Measured (CAR, t, ...) for one event and security, or None if not realized."""
        ctx = self._context(as_of)
        ev = ctx.by_id.get(event_id)
        return None if ev is None else self._study(ctx, ev, security_id)

    # ---- context -------------------------------------------------------------------------
    def _context(self, as_of: datetime) -> _Context:
        as_of = ensure_utc(as_of)
        key = (as_of, self.store.latest_as_of())  # a fetch that adds data invalidates the entry
        if key in self._cache:
            self._cache.move_to_end(key)
            return self._cache[key]
        ids = list(dict.fromkeys(self.banks + [self.sector_bm_id, self.market_id]))
        rets = self.store.returns(ids, as_of)
        rets = rets.reindex(columns=ids)
        stored = self.store.events(as_of)
        derived = self._derive_shocks(rets, stored)
        seen = {e.event_id for e in stored}
        events = list(stored) + [e for e in derived if e.event_id not in seen]
        events.sort(key=lambda e: (event_time(e), e.event_id))
        ctx = _Context(as_of=as_of, returns=rets, dates=pd.DatetimeIndex(rets.index),
                       stored=stored, events=events, by_id={e.event_id: e for e in events})
        self._cache[key] = ctx
        if len(self._cache) > self._cache_size:
            self._cache.popitem(last=False)
        return ctx

    # ---- derived price shocks ------------------------------------------------------------
    def _derive_shocks(self, rets: pd.DataFrame, stored: list[Event]) -> list[Event]:
        """Firm shocks: abnormal return vs XLF (60-day rolling market model) beyond 3 residual
        std. devs AND beyond 3% in size.

        Second tier (sector-wide days): XLF contains the banks, so a sector-wide move is
        mostly absorbed by an XLF benchmark. On days when XLF itself passes the same test
        against SPY, each bank is also tested against SPY with the same thresholds.
        """
        if rets.empty or len(rets) <= SHOCK_WINDOW:
            return []
        xlf, spy = rets.get(self.sector_bm_id), rets.get(self.market_id)
        if xlf is None or xlf.isna().all():
            return []
        sector_days = pd.Series(False, index=rets.index)
        if spy is not None and not spy.isna().all():
            s = rolling_abnormal(xlf, spy, SHOCK_WINDOW)
            sector_days = (s["z"].abs() > SHOCK_Z) & (s["ar"].abs() > SHOCK_MIN_ABS)

        hits: dict[pd.Timestamp, list[tuple[str, float, float, str]]] = {}
        for sid in self.banks:
            if sid not in rets.columns or rets[sid].isna().all():
                continue
            a = rolling_abnormal(rets[sid], xlf, SHOCK_WINDOW)
            firm = (a["z"].abs() > SHOCK_Z) & (a["ar"].abs() > SHOCK_MIN_ABS)
            for ts in firm.index[firm.to_numpy()]:
                hits.setdefault(ts, []).append(
                    (sid, float(a.at[ts, "ar"]), float(a.at[ts, "z"]), self.sector_bm_id))
            if spy is None or not sector_days.any():
                continue
            b = rolling_abnormal(rets[sid], spy, SHOCK_WINDOW)
            tier2 = sector_days & ~firm & (b["z"].abs() > SHOCK_Z) & (b["ar"].abs() > SHOCK_MIN_ABS)
            for ts in tier2.index[tier2.to_numpy()]:
                hits.setdefault(ts, []).append(
                    (sid, float(b.at[ts, "ar"]), float(b.at[ts, "z"]), self.market_id))

        stored_by_day: dict[date, list[Event]] = {}
        for e in stored:
            stored_by_day.setdefault(event_day(event_time(e)), []).append(e)

        out: list[Event] = []
        for ts in sorted(hits):
            d = ts.date()
            same_day = stored_by_day.get(d, [])
            for sid, ar, z, bm in sorted(hits[ts]):
                canon = _canonical(same_day, lambda e, s=sid: s in e.affected_security_ids)
                out.append(self._shock_event(d, sid, ar, z, bm, canon))
            shocked = sorted(h[0] for h in hits[ts])
            if len(shocked) >= SECTOR_MIN_BANKS:
                canon = _canonical(same_day, lambda e: e.scope in (EventScope.SECTOR,
                                                                    EventScope.MARKET))
                out.append(self._sector_event(d, hits[ts], canon))
        return out

    def _shock_event(self, d: date, sid: str, ar: float, z: float, bm: str,
                     canon: str | None) -> Event:
        avail = bar_available_at(d)
        return Event(
            source_id=DERIVED_SOURCE,
            origin=DataOrigin.DERIVED,
            available_at=avail,
            event_id=f"shock-{sid}-{d.isoformat()}",
            event_class=EventClass.UNEXPECTED,
            subtype="price_shock",
            title=f"{sid} price shock {ar:+.1%} vs {bm} (z={z:+.1f})",
            status=EventStatus.OCCURRED,
            scope=EventScope.FIRM,
            occurred_at=et(d, 16, 0),
            published_at=avail,
            affected_security_ids=[sid],
            source_ids=[f"derived:price_shock:{sid}:{d.isoformat()}"],
            actual_outcome=(
                f"Abnormal return {ar:+.2%} vs {bm}, {z:+.1f} residual std. devs "
                f"(60-day market model)"
            ),
            surprise=round(ar, 6),
            canonical_event_id=canon,
        )

    def _sector_event(self, d: date, hits: list[tuple[str, float, float, str]],
                      canon: str | None) -> Event:
        avail = bar_available_at(d)
        names = ", ".join(f"{s} {ar:+.1%}" for s, ar, _, _ in sorted(hits))
        mean_ar = float(np.mean([h[1] for h in hits]))
        return Event(
            source_id=DERIVED_SOURCE,
            origin=DataOrigin.DERIVED,
            available_at=avail,
            event_id=f"shock-sector-{d.isoformat()}",
            event_class=EventClass.UNEXPECTED,
            subtype="price_shock",
            title=f"Sector price shock: {len(hits)} banks on {d.isoformat()}",
            status=EventStatus.OCCURRED,
            scope=EventScope.SECTOR,
            occurred_at=et(d, 16, 0),
            published_at=avail,
            affected_security_ids=list(self.banks),
            source_ids=[f"derived:price_shock:shock-{h[0]}-{d.isoformat()}"
                        for h in sorted(hits)],
            actual_outcome=f"Banks with shocks: {names}",
            surprise=round(mean_ar, 6),
            canonical_event_id=canon,
        )

    # ---- impact estimates ------------------------------------------------------------------
    def _benchmark_for(self, sid: str, ev: Event) -> str:
        """XLF for firm-scope events. SPY for sector/market-scope events (XLF holds the banks,
        so it would absorb a sector-wide move) and for XLF itself."""
        if sid == self.sector_bm_id or ev.scope != EventScope.FIRM:
            return self.market_id
        return self.sector_bm_id

    def _t0(self, ctx: _Context, ev: Event) -> int | None:
        return day_index(ctx.dates, event_day(event_time(ev)))

    def _is_complete(self, ctx: _Context, ev: Event) -> bool:
        """The event window [-1, +1] has closed, so the CAR can be measured."""
        t0 = self._t0(ctx, ev)
        return t0 is not None and t0 + CAR_END < len(ctx.dates)

    def _drift_complete(self, ctx: _Context, ev: Event) -> bool:
        """The post-event drift window [+2, +20] has also closed."""
        t0 = self._t0(ctx, ev)
        return t0 is not None and t0 + DRIFT_END < len(ctx.dates)

    def _study(self, ctx: _Context, ev: Event, sid: str) -> StudyResult | None:
        key = (ev.event_id, sid)
        if key in ctx.studies:
            return ctx.studies[key]
        res = None
        bm = self._benchmark_for(sid, ev)
        if self._is_complete(ctx, ev) and sid in ctx.returns.columns and bm in ctx.returns:
            t0 = self._t0(ctx, ev)
            y = ctx.returns[sid].to_numpy(dtype=float)
            x = ctx.returns[bm].to_numpy(dtype=float)
            res = market_model_study(y, x, t0)
        ctx.studies[key] = res
        return res

    def _estimate(self, ctx: _Context, ev: Event, sid: str, weight: float) -> ImpactEstimate:
        bm = self._benchmark_for(sid, ev)
        common = {
            "event_id": ev.event_id,
            "security_id": sid,
            "window_pre_days": -CAR_START,
            "window_post_days": CAR_END,
            "duration_days": DRIFT_END,
            "benchmark_id": bm,
            "as_of": ctx.as_of,
        }
        wnote = f" Exposure weight {weight:.2f}." if weight != 1.0 else ""
        if sid not in ctx.returns.columns or (sid == self.market_id):
            return ImpactEstimate(**common, realized=False, direction=Direction.UNKNOWN,
                                  method="none", confidence=Confidence.UNAVAILABLE,
                                  note=f"No benchmark-adjusted study for {sid}. {NOTE}")
        if self._is_complete(ctx, ev):
            res = self._study(ctx, ev, sid)
            if res is None:
                return ImpactEstimate(
                    **common, realized=True, direction=Direction.UNKNOWN,
                    method=STUDY_METHOD.format(bm=bm), confidence=Confidence.UNAVAILABLE,
                    evidence_ids=[ev.event_id],
                    note=f"Too little estimation history (needs 60+ days). {NOTE}")
            conf = Confidence.MEDIUM if res.n_est >= MEDIUM_EST_OBS else Confidence.LOW
            drift_done = self._drift_complete(ctx, ev)
            drift_note = "" if drift_done else " Post-event drift window still open."
            return ImpactEstimate(
                **common, realized=True, direction=_direction(res.car, res.t_stat),
                abnormal_return=res.car, event_day_return=res.event_day_return,
                post_event_drift=res.post_drift if drift_done else None, t_stat=res.t_stat,
                expected_return_impact=res.car, uncertainty=res.sigma * np.sqrt(3),
                method=STUDY_METHOD.format(bm=bm), sample_size=res.n_est, confidence=conf,
                evidence_ids=_evidence(ev),
                note=(f"Measured after the event window closed; beta {res.beta:.2f} on "
                      f"{res.n_est} estimation days.{drift_note}{wnote} {NOTE}"),
            )
        return self._forward(ctx, ev, sid, weight, common, wnote)

    def _forward(self, ctx: _Context, ev: Event, sid: str, weight: float, common: dict,
                 wnote: str) -> ImpactEstimate:
        this_day = event_day(event_time(ev))
        hist_ids, cars = [], []
        for h in ctx.events:
            if h.event_id == ev.event_id or h.subtype != ev.subtype or h.scope != ev.scope:
                continue
            if sid not in h.affected_security_ids or h.canonical_event_id == ev.event_id:
                continue
            if event_day(event_time(h)) >= this_day:
                continue
            res = self._study(ctx, h, sid)
            if res is not None:
                hist_ids.append(h.event_id)
                cars.append(res.car)
        n = len(cars)
        conf = (Confidence.HIGH if n >= FWD_HIGH else Confidence.MEDIUM if n >= FWD_MEDIUM
                else Confidence.LOW if n >= FWD_LOW else Confidence.UNAVAILABLE)
        method = FORWARD_METHOD.format(bm=common["benchmark_id"])
        if conf == Confidence.UNAVAILABLE:
            return ImpactEstimate(
                **common, realized=False, direction=Direction.UNKNOWN, method=method,
                sample_size=n, confidence=conf, evidence_ids=hist_ids,
                note=(f"Event window not complete as of this time and only {n} past "
                      f"'{ev.subtype}' event(s) measured for {sid}; no estimate. {NOTE}"))
        arr = np.asarray(cars)
        mean, sd = float(arr.mean()), float(arr.std(ddof=1))
        se = sd / np.sqrt(n) if sd > 0 else 0.0
        t = mean / se if se > 0 else 0.0
        return ImpactEstimate(
            **common, realized=False, direction=_direction(mean, t),
            abnormal_return=None, expected_return_impact=weight * mean,
            uncertainty=weight * sd, t_stat=t, method=method, sample_size=n, confidence=conf,
            evidence_ids=hist_ids,
            note=(f"Forward estimate: mean CAR of {n} past '{ev.subtype}' events for {sid}."
                  f"{wnote} {NOTE}"),
        )


def _direction(value: float, t_stat: float) -> Direction:
    if not np.isfinite(value):
        return Direction.UNKNOWN
    if abs(t_stat) < T_CRIT:
        return Direction.NEUTRAL
    return Direction.UP if value > 0 else Direction.DOWN


def _evidence(ev: Event) -> list[str]:
    return [ev.event_id] + ([ev.canonical_event_id] if ev.canonical_event_id else [])


def _canonical(candidates: list[Event], pred) -> str | None:
    """Stored event on the same day that matches ``pred``; firm scope first, then by id."""
    m = [e for e in candidates if pred(e)]
    if not m:
        return None
    m.sort(key=lambda e: (_SCOPE_RANK.get(e.scope, 9), e.event_id))
    return m[0].event_id


def _takes_returns(module) -> bool:
    import inspect

    try:
        return "returns" in inspect.signature(module.exposure).parameters
    except (TypeError, ValueError):
        return False

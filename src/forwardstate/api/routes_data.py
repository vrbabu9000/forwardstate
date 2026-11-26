"""Read-only data routes: securities, prices, peers, events, analysts, fundamentals, macro."""

from __future__ import annotations

import math
from datetime import date
from typing import Annotated

import numpy as np
import pandas as pd
from fastapi import APIRouter, Query

from forwardstate.contracts import (
    AnalystObservation,
    DataOrigin,
    Event,
    EventClass,
    ImpactEstimate,
    Observation,
    PeerComparison,
    PeerSeries,
    PricePoint,
    PriceSeries,
    RebasedPoint,
    Security,
    SecurityRole,
)

from .asof import AsOfRoute, parse_as_of
from .context import AppContext, Ctx
from .errors import invalid, not_found

router = APIRouter(prefix="/api", route_class=AsOfRoute)

TRADING_DAYS_PER_YEAR = 252
MIN_PEER_POINTS = 3  # need at least two daily returns for a volatility
MAX_PEERS = 4
# The sector ETF used as the peer-chart benchmark. Other sectors fall back to all benchmarks.
SECTOR_BENCHMARK = {"financials": "XLF"}
# Used when the caller gives no metric_id. Named here so the default is visible, not hidden.
DEFAULT_FUNDAMENTAL_METRICS = ["eps_actual", "eps_estimate", "eps_surprise_pct"]
DEFAULT_MACRO_METRICS = ["DFF", "DGS2", "DGS10"]


def _securities(ctx: AppContext) -> dict[str, Security]:
    return {s.security_id: s for s in ctx.services().store.securities()}


def _require_security(ctx: AppContext, security_id: str, field: str = "security_id") -> Security:
    sec = _securities(ctx).get(security_id)
    if sec is None:
        raise not_found("security", security_id, field)
    return sec


def _check_range(start: date | None, end: date | None) -> None:
    if start and end and start > end:
        raise invalid(f"start {start} is after end {end}", "start")


def _origin_of(values: pd.Series, fallback: DataOrigin) -> DataOrigin:
    """The weakest origin present: synthetic beats derived beats real."""
    found = {str(v) for v in values.dropna().unique()}
    for o in (DataOrigin.SYNTHETIC, DataOrigin.DERIVED, DataOrigin.REAL):
        if o.value in found:
            return o
    return fallback


def _opt_float(v: object) -> float | None:
    if v is None:
        return None
    f = float(v)  # type: ignore[arg-type]
    return None if math.isnan(f) else f


@router.get("/securities", response_model=list[Security])
def list_securities(ctx: Ctx, sector: str | None = None) -> list[Security]:
    return ctx.services().store.securities(sector)


@router.get("/prices/{security_id}", response_model=PriceSeries)
def get_prices(
    ctx: Ctx,
    security_id: str,
    start: date | None = None,
    end: date | None = None,
    as_of: str | None = None,
) -> PriceSeries:
    _check_range(start, end)
    _require_security(ctx, security_id)
    ts = ctx.resolve_as_of(parse_as_of(as_of))
    svc = ctx.services()
    df = svc.store.prices([security_id], ts, start, end)
    points = [
        PricePoint(
            date=pd.Timestamp(r.trading_date).date(),
            close=float(r.adj_close),
            raw_close=float(r.raw_close),
            volume=_opt_float(r.volume),
        )
        for r in df.itertuples(index=False)
    ]
    origin = _origin_of(df["origin"], svc.data_origin) if len(df) else svc.data_origin
    return PriceSeries(security_id=security_id, as_of=ts, origin=origin, points=points)


def _peer_ids(ctx: AppContext, focal: Security, sector_id: str) -> list[str]:
    secs = [s for s in ctx.services().store.securities(focal.sector)]
    peers = [
        s.security_id
        for s in secs
        if s.role in (SecurityRole.FOCAL, SecurityRole.PEER) and s.security_id != focal.security_id
    ][:MAX_PEERS]
    bench_id = SECTOR_BENCHMARK.get(sector_id)
    benches = [
        s.security_id
        for s in secs
        if s.role == SecurityRole.BENCHMARK and (bench_id is None or s.security_id == bench_id)
    ]
    return [focal.security_id, *peers, *[b for b in benches if b != focal.security_id]]


def _peer_series(security_id: str, values: pd.Series) -> PeerSeries:
    rets = values.pct_change(fill_method=None).dropna()
    drawdown = 1.0 - values / values.cummax()
    return PeerSeries(
        security_id=security_id,
        points=[RebasedPoint(date=d.date(), value=float(v)) for d, v in values.items()],
        total_return=float(values.iloc[-1] / values.iloc[0] - 1.0),
        volatility_annual=float(rets.std(ddof=1) * np.sqrt(TRADING_DAYS_PER_YEAR)),
        max_drawdown=float(drawdown.max()),
    )


@router.get("/peers/{security_id}", response_model=PeerComparison)
def get_peers(
    ctx: Ctx,
    security_id: str,
    start: date | None = None,
    end: date | None = None,
    as_of: str | None = None,
) -> PeerComparison:
    """Focal + peers + sector ETF, rebased to 100 at the first date all of them have a price.

    Securities with no prices at all in the window are left out (they cannot be rebased).
    Fewer than three common dates gives an empty comparison rather than made-up metrics.
    """
    _check_range(start, end)
    focal = _require_security(ctx, security_id)
    ts = ctx.resolve_as_of(parse_as_of(as_of))
    svc = ctx.services()
    ids = _peer_ids(ctx, focal, svc.sector_id)
    df = svc.store.prices(ids, ts, start, end)
    empty = PeerComparison(focal_id=security_id, base_date=None, as_of=ts, series=[])
    if df.empty:
        return empty
    wide = df.pivot(index="trading_date", columns="security_id", values="adj_close").sort_index()
    present = [i for i in ids if i in wide.columns and wide[i].notna().any()]
    if security_id not in present:
        return empty
    common = wide[present].dropna(how="any")
    if len(common) < MIN_PEER_POINTS:
        return empty
    rebased = common / common.iloc[0] * 100.0
    return PeerComparison(
        focal_id=security_id,
        base_date=common.index[0].date(),
        as_of=ts,
        series=[_peer_series(i, rebased[i]) for i in present],
    )


@router.get("/events", response_model=list[Event])
def list_events(
    ctx: Ctx,
    security_id: Annotated[list[str] | None, Query()] = None,
    event_class: Annotated[list[EventClass] | None, Query()] = None,
    start: date | None = None,
    end: date | None = None,
    as_of: str | None = None,
) -> list[Event]:
    _check_range(start, end)
    ts = ctx.resolve_as_of(parse_as_of(as_of))
    return ctx.services().events.list_events(ts, security_id or None, event_class or None, start, end)


@router.get("/events/{event_id}/impact", response_model=list[ImpactEstimate])
def get_event_impact(
    ctx: Ctx,
    event_id: str, as_of: str | None = None
) -> list[ImpactEstimate]:
    ts = ctx.resolve_as_of(parse_as_of(as_of))
    svc = ctx.services()
    if not any(e.event_id == event_id for e in svc.events.list_events(ts)):
        raise not_found("event (as of the requested time)", event_id, "event_id")
    return svc.events.impact_estimates(ts, event_id=event_id)


@router.get("/analysts", response_model=list[AnalystObservation])
def list_analysts(
    ctx: Ctx,
    security_id: str | None = None, as_of: str | None = None
) -> list[AnalystObservation]:
    if security_id:
        _require_security(ctx, security_id)
    ts = ctx.resolve_as_of(parse_as_of(as_of))
    return ctx.services().store.analyst_observations(ts, [security_id] if security_id else None)


@router.get("/fundamentals", response_model=list[Observation])
def list_fundamentals(
    ctx: Ctx,
    security_id: str | None = None,
    metric_id: Annotated[list[str] | None, Query()] = None,
    as_of: str | None = None,
) -> list[Observation]:
    if security_id:
        _require_security(ctx, security_id)
    ts = ctx.resolve_as_of(parse_as_of(as_of))
    obs = ctx.services().store.observations(
        metric_id or DEFAULT_FUNDAMENTAL_METRICS, ts, security_id=security_id
    )
    return [o for o in obs if o.security_id is not None]


@router.get("/macro", response_model=list[Observation])
def list_macro(
    ctx: Ctx,
    metric_id: Annotated[list[str] | None, Query()] = None,
    start: date | None = None,
    as_of: str | None = None,
) -> list[Observation]:
    ts = ctx.resolve_as_of(parse_as_of(as_of))
    obs = ctx.services().store.observations(metric_id or DEFAULT_MACRO_METRICS, ts, start=start)
    return [o for o in obs if o.security_id is None]

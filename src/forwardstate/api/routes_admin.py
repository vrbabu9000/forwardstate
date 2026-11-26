"""Health, meta, sources, settings and run provenance routes."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from forwardstate import __version__
from forwardstate.contracts import Meta, ReproduceResult, RunKind, RunRecord, Settings, SourceStatus

from .asof import AsOfRoute
from .compute import rerun
from .context import Ctx
from .errors import not_found

router = APIRouter(prefix="/api", route_class=AsOfRoute)


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/meta", response_model=Meta)
def get_meta(ctx: Ctx) -> Meta:
    svc = ctx.services()
    return Meta(version=__version__, data_origin=svc.data_origin, sector=svc.sector_id)


@router.get("/sources", response_model=list[SourceStatus])
def list_sources(ctx: Ctx) -> list[SourceStatus]:
    return ctx.services().store.source_status()


@router.get("/settings", response_model=Settings)
def get_settings(ctx: Ctx) -> Settings:
    return ctx.settings.get()


@router.put("/settings", response_model=Settings)
def put_settings(ctx: Ctx, body: Settings) -> Settings:
    svc = ctx.services()  # fail with 503 before saving if the engines are not available
    saved = ctx.settings.put(body)
    svc.apply_settings(saved)
    return saved


@router.get("/runs", response_model=list[RunRecord])
def list_runs(
    ctx: Ctx,
    kind: RunKind | None = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 50,
) -> list[RunRecord]:
    return ctx.runs.list(kind, limit)


@router.get("/runs/{run_id}", response_model=RunRecord)
def get_run(ctx: Ctx, run_id: str) -> RunRecord:
    rec = ctx.runs.get(run_id)
    if rec is None:
        raise not_found("run", run_id, "run_id")
    return rec


@router.post("/runs/{run_id}/reproduce", response_model=ReproduceResult)
def reproduce_run(ctx: Ctx, run_id: str) -> ReproduceResult:
    if run_id not in ctx.runs:
        raise not_found("run", run_id, "run_id")
    return ctx.runs.reproduce(run_id, lambda rec: rerun(ctx, rec))

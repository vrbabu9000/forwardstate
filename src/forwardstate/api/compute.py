"""Computing POSTs (forecast, portfolio, alerts, replay) and their run provenance (AC-06)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from forwardstate.contracts import (
    CONTRACT_VERSION,
    Alert,
    AlertsRequest,
    ForecastRequest,
    ForecastRun,
    PortfolioEvaluation,
    PortfolioRequest,
    ReplayRequest,
    ReplayResult,
    RunKind,
    RunRecord,
    stable_hash,
)
from forwardstate.pit import NY, as_of_for_date, ensure_utc

from .context import AppContext
from .errors import ApiError, invalid
from .runs import output_hash

REQUEST_TYPES: dict[RunKind, type] = {
    RunKind.FORECAST: ForecastRequest,
    RunKind.PORTFOLIO: PortfolioRequest,
    RunKind.OPTIMIZE: PortfolioRequest,
    RunKind.ALERTS: AlertsRequest,
    RunKind.REPLAY: ReplayRequest,
}

Response = ForecastRun | PortfolioEvaluation | ReplayResult | list[Alert]


def _check_rule_ids(ctx: AppContext, rule_ids: list[str] | None) -> None:
    if not rule_ids:
        return
    known = {r.rule_id for r in ctx.services().alerts.rules()}
    unknown = sorted(set(rule_ids) - known)
    if unknown:
        raise invalid(f"Unknown alert rule_id: {', '.join(unknown)}", "rule_ids")


def _execute(ctx: AppContext, kind: RunKind, req: Any, as_of: datetime) -> Response:
    svc = ctx.services()
    if kind == RunKind.FORECAST:
        if not req.security_ids:
            raise invalid("security_ids must not be empty", "security_ids")
        if not req.horizons:
            raise invalid("horizons must not be empty", "horizons")
        known = {s.security_id for s in svc.store.securities()}
        unknown = [s for s in req.security_ids if s not in known]
        if unknown:
            raise invalid(f"Unknown security_id: {', '.join(unknown)}", "security_ids")
        return svc.forecaster.forecast(as_of, req.security_ids, req.horizons, req.assumptions)
    if kind == RunKind.PORTFOLIO:
        return svc.portfolio.evaluate_portfolio(req.portfolio, as_of, req.assumptions)
    if kind == RunKind.OPTIMIZE:
        return svc.portfolio.optimize(req.portfolio, as_of, req.assumptions)
    if kind == RunKind.ALERTS:
        _check_rule_ids(ctx, req.rule_ids)
        return svc.alerts.evaluate_alerts(req.portfolio, as_of, req.assumptions, req.rule_ids)
    if kind == RunKind.REPLAY:
        if req.start > req.end:
            raise invalid(f"start {req.start} is after end {req.end}", "start")
        _check_rule_ids(ctx, req.rule_ids)
        return svc.alerts.replay(
            req.portfolio, req.start, req.end, req.assumptions, req.step_trading_days, req.rule_ids
        )
    raise invalid(f"Unknown run kind {kind}")  # pragma: no cover


def _engine_run_id(resp: Response) -> str | None:
    if isinstance(resp, list):
        ids = [a.run_id for a in resp if a.run_id]
        return ids[0] if ids else None
    return getattr(resp, "run_id", None) or None


def _with_run_id(resp: Response, run_id: str) -> Response:
    if isinstance(resp, list):
        return [a if a.run_id == run_id else a.model_copy(update={"run_id": run_id}) for a in resp]
    if resp.run_id == run_id:
        return resp
    return resp.model_copy(update={"run_id": run_id})


def _model_version(ctx: AppContext, resp: Response) -> str:
    if isinstance(resp, list):
        # Alerts have no top-level model_version in the contract: ask the engine.
        return str(getattr(ctx.services().alerts, "model_version", None) or "unversioned")
    return resp.model_version


def input_hash(request_json: dict[str, Any], as_of: datetime, sources: list[dict]) -> str:
    """Hash of request + resolved as_of + source status. The request's own ``as_of`` is left out
    (the resolved one is hashed instead), so 'latest' and the explicit same instant match."""
    req = {k: v for k, v in request_json.items() if k != "as_of"}
    as_of_day = as_of.astimezone(NY).date().isoformat()
    # Only what the run could see: each source's latest record date, capped at as_of.
    # Health, fetch times and counts change with wall-clock time and later fetches.
    seen = sorted(
        (s.get("source_id"), min(s["latest_record_date"], as_of_day) if s.get("latest_record_date") else None)
        for s in sources
    )
    return stable_hash({"request": req, "as_of": as_of, "sources_seen": seen})


def run_compute(ctx: AppContext, kind: RunKind, req: Any) -> tuple[Response, RunRecord]:
    """Run one computing request, record it, and return (response, record)."""
    svc = ctx.services()
    settings = ctx.settings.get()
    if kind == RunKind.REPLAY:
        as_of = as_of_for_date(req.end)
    else:
        as_of = ctx.resolve_as_of(req.as_of)
    latest = ctx.latest_as_of()
    try:
        resp = _execute(ctx, kind, req, as_of)
    except ApiError:
        raise
    except (ValueError, KeyError) as e:
        raise ApiError(422, "rejected_by_engine", f"{type(e).__name__}: {e}") from e

    run_id = _engine_run_id(resp)
    if not run_id or run_id in ctx.runs:
        run_id = uuid.uuid4().hex
    resp = _with_run_id(resp, run_id)

    cutoff = getattr(resp, "data_cutoff", None)
    data_cutoff = ensure_utc(cutoff) if cutoff else min(as_of, latest)
    sources = [s.model_dump(mode="json") for s in svc.store.source_status()]
    request_json = req.model_dump(mode="json")
    record = RunRecord(
        run_id=run_id,
        kind=kind,
        created_at=datetime.now(timezone.utc),
        as_of=as_of,
        data_cutoff=data_cutoff,
        model_version=_model_version(ctx, resp),
        contract_version=CONTRACT_VERSION,
        config_hash=stable_hash(settings),
        input_hash=input_hash(request_json, as_of, sources),
        output_hash=output_hash(resp),
        request=request_json,
        data_origin=svc.data_origin,
        source_status=sources,
    )
    ctx.runs.add(record)
    return resp, record


def rerun(ctx: AppContext, record: RunRecord) -> tuple[RunRecord, list[str]]:
    """Re-run a stored request with its original as_of (used by RunRegistry.reproduce)."""
    req = REQUEST_TYPES[record.kind].model_validate(record.request)
    if record.kind != RunKind.REPLAY:
        req = req.model_copy(update={"as_of": record.as_of})
    _, new = run_compute(ctx, record.kind, req)
    return new, []

"""Computing routes. Each one records a RunRecord; the response's run_id matches it and is also
sent in the ``X-Run-Id`` header (useful when an alert evaluation returns an empty list)."""

from __future__ import annotations

from fastapi import APIRouter, Response

from forwardstate.contracts import (
    Alert,
    AlertRule,
    AlertsRequest,
    AlertStatus,
    ForecastRequest,
    ForecastRun,
    PortfolioEvaluation,
    PortfolioRequest,
    ReplayRequest,
    ReplayResult,
    RunKind,
    TransitionRequest,
)

from .asof import AsOfRoute
from .compute import run_compute
from .context import AppContext, Ctx
from .errors import invalid, not_found

router = APIRouter(prefix="/api", route_class=AsOfRoute)


def _run(ctx: AppContext, kind: RunKind, req: object, response: Response):
    resp, record = run_compute(ctx, kind, req)
    response.headers["X-Run-Id"] = record.run_id
    return resp


@router.post("/forecast", response_model=ForecastRun)
def post_forecast(
    ctx: Ctx,
    req: ForecastRequest, response: Response
) -> ForecastRun:
    return _run(ctx, RunKind.FORECAST, req, response)


@router.post("/portfolio/evaluate", response_model=PortfolioEvaluation)
def post_portfolio_evaluate(
    ctx: Ctx,
    req: PortfolioRequest, response: Response
) -> PortfolioEvaluation:
    return _run(ctx, RunKind.PORTFOLIO, req, response)


@router.post("/portfolio/optimize", response_model=PortfolioEvaluation)
def post_portfolio_optimize(
    ctx: Ctx,
    req: PortfolioRequest, response: Response
) -> PortfolioEvaluation:
    return _run(ctx, RunKind.OPTIMIZE, req, response)


@router.get("/alerts/rules", response_model=list[AlertRule])
def get_alert_rules(ctx: Ctx) -> list[AlertRule]:
    return ctx.services().alerts.rules()


@router.post("/alerts/evaluate", response_model=list[Alert])
def post_alerts_evaluate(
    ctx: Ctx,
    req: AlertsRequest, response: Response
) -> list[Alert]:
    return _run(ctx, RunKind.ALERTS, req, response)


@router.get("/alerts", response_model=list[Alert])
def list_alerts(ctx: Ctx, status: AlertStatus | None = None) -> list[Alert]:
    return ctx.services().alerts.list_alerts(status)


@router.post("/alerts/{alert_id}/transition", response_model=Alert)
def post_alert_transition(
    ctx: Ctx,
    alert_id: str, req: TransitionRequest
) -> Alert:
    try:
        return ctx.services().alerts.transition(alert_id, req.to_status, req.note)
    except KeyError as e:
        raise not_found("alert", alert_id, "alert_id") from e
    except ValueError as e:
        raise invalid(str(e), "to_status", "invalid_transition") from e


@router.post("/replay", response_model=ReplayResult)
def post_replay(
    ctx: Ctx,
    req: ReplayRequest, response: Response
) -> ReplayResult:
    return _run(ctx, RunKind.REPLAY, req, response)

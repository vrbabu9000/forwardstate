"""AC-06: the API has no trade capability. Every route is listed and checked."""

from __future__ import annotations

import re

from fastapi.routing import APIRoute

from forwardstate.api.app import app, create_app
from forwardstate.api.fakes import fake_services
from forwardstate.contracts import DECISION_BOUNDARY

FORBIDDEN = ("order", "trade", "execute", "broker", "buy", "sell")

EXPECTED = {
    ("GET", "/api/health"), ("GET", "/api/meta"), ("GET", "/api/sources"),
    ("GET", "/api/securities"), ("GET", "/api/prices/{security_id}"),
    ("GET", "/api/peers/{security_id}"), ("GET", "/api/events"),
    ("GET", "/api/events/{event_id}/impact"), ("GET", "/api/analysts"),
    ("GET", "/api/fundamentals"), ("GET", "/api/macro"), ("POST", "/api/forecast"),
    ("POST", "/api/portfolio/evaluate"), ("POST", "/api/portfolio/optimize"),
    ("GET", "/api/alerts/rules"), ("POST", "/api/alerts/evaluate"), ("GET", "/api/alerts"),
    ("POST", "/api/alerts/{alert_id}/transition"), ("POST", "/api/replay"),
    ("GET", "/api/settings"), ("PUT", "/api/settings"), ("GET", "/api/runs"),
    ("GET", "/api/runs/{run_id}"), ("POST", "/api/runs/{run_id}/reproduce"),
}


def _walk(routes):
    for r in routes:
        if isinstance(r, APIRoute):
            yield r
        inner = getattr(r, "original_router", None) or getattr(r, "routes", None)
        if inner is not None and not isinstance(r, APIRoute):
            yield from _walk(getattr(inner, "routes", inner))


def _routes(a):
    return list(_walk(a.routes))


# The built web UI (if present) is served by one GET-only static fallback; it is not an API route.
UI_ROUTES = {("GET", "/{path:path}")}


def test_route_set_is_exactly_the_spec():
    got = {(m, r.path) for r in _routes(app) for m in r.methods} - UI_ROUTES
    assert got == EXPECTED
    in_openapi = {(m.upper(), p) for p, ops in app.openapi()["paths"].items() for m in ops}
    assert in_openapi == EXPECTED


def test_no_trading_words_in_paths_or_operations():
    words = re.compile("|".join(FORBIDDEN), re.IGNORECASE)
    for a in (app, create_app(fake_services())):
        routes = _routes(a)
        assert routes
        for r in routes:
            for text in (r.path, r.name, r.unique_id, r.endpoint.__name__):
                assert not words.search(text), f"trading word in route {r.path}: {text}"
        for path, ops in a.openapi()["paths"].items():
            assert not words.search(path)
            for op in ops.values():
                assert not words.search(op.get("operationId", ""))
                assert not words.search(op.get("summary", ""))


def test_no_delete_or_patch_methods():
    assert not {m for r in _routes(app) for m in r.methods} & {"DELETE", "PATCH"}


def test_disclaimer_in_openapi():
    assert app.openapi()["info"]["description"] == DECISION_BOUNDARY

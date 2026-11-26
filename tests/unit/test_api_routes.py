"""API routes over FixtureStore + test-only fake engines (no real engines needed)."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from pydantic import TypeAdapter

from forwardstate.api.app import create_app
from forwardstate.api.fakes import fake_services
from forwardstate.api.settings_store import default_settings
from forwardstate.contracts import (
    DECISION_BOUNDARY,
    Alert,
    AlertRule,
    AnalystObservation,
    Event,
    ForecastRun,
    ImpactEstimate,
    Meta,
    Observation,
    PeerComparison,
    PortfolioEvaluation,
    PriceSeries,
    ReplayResult,
    Security,
    Settings,
    SourceStatus,
)
from forwardstate.pit import as_of_for_date
from forwardstate.testing import FixtureStore

PORTFOLIO = {
    "total_value": 100000,
    "holdings": [
        {"security_id": "JPM", "weight": 0.5},
        {"security_id": "BAC", "weight": 0.4},
        {"security_id": "CASH", "weight": 0.1},
    ],
}


@pytest.fixture(scope="module")
def store() -> FixtureStore:
    return FixtureStore()


@pytest.fixture()
def client(store, tmp_path) -> TestClient:
    rules = default_settings().alert_rules
    app = create_app(fake_services(store, rules), state_dir=tmp_path)
    return TestClient(app)


def _v(tp, data):
    return TypeAdapter(tp).validate_python(data)


def test_health(client):
    assert client.get("/api/health").json() == {"status": "ok"}


def test_meta_says_synthetic_with_fixture(client):
    meta = _v(Meta, client.get("/api/meta").json())
    assert meta.data_origin.value == "synthetic"
    assert meta.sector == "financials"
    assert meta.disclaimer == DECISION_BOUNDARY


def test_sources_and_securities(client):
    src = _v(list[SourceStatus], client.get("/api/sources").json())
    assert src[0].source_id == "synthetic"
    secs = _v(list[Security], client.get("/api/securities?sector=financials").json())
    assert {"JPM", "BAC", "C", "MS", "GS", "SPY", "XLF", "CASH"} <= {s.security_id for s in secs}
    assert client.get("/api/securities?sector=nope").json() == []


def test_prices(client):
    r = client.get("/api/prices/JPM?start=2024-01-02&end=2024-01-31")
    assert r.status_code == 200
    ps = _v(PriceSeries, r.json())
    assert ps.origin.value == "synthetic"
    assert ps.points and all(p.close > 0 and p.raw_close > 0 for p in ps.points)
    assert ps.points[0].date.isoformat() >= "2024-01-02"
    assert ps.points[-1].date.isoformat() <= "2024-01-31"


def test_prices_respects_as_of(client):
    ps = _v(PriceSeries, client.get("/api/prices/JPM?start=2023-01-01&as_of=2023-03-10").json())
    assert ps.points[-1].date.isoformat() == "2023-03-10"
    assert ps.as_of == as_of_for_date(datetime(2023, 3, 10).date())


def test_peers_rebased(client):
    pc = _v(PeerComparison, client.get("/api/peers/JPM?start=2024-01-01").json())
    ids = [s.security_id for s in pc.series]
    assert ids[0] == "JPM"
    assert set(ids) == {"JPM", "BAC", "C", "MS", "GS", "XLF"}
    for s in pc.series:
        assert s.points[0].value == pytest.approx(100.0)
        assert s.points[0].date == pc.base_date
        assert s.total_return == pytest.approx(s.points[-1].value / 100 - 1)
        assert s.volatility_annual > 0
        assert 0 <= s.max_drawdown < 1


def test_peers_too_little_data_is_empty_not_invented(client):
    pc = _v(PeerComparison, client.get("/api/peers/JPM?start=2024-12-31").json())
    assert pc.series == [] and pc.base_date is None


def test_events_and_impact(client):
    evs = _v(list[Event], client.get("/api/events?security_id=JPM&as_of=2023-06-30").json())
    assert evs and all("JPM" in e.affected_security_ids for e in evs)
    assert all(e.available_at <= as_of_for_date(datetime(2023, 6, 30).date()) for e in evs)
    sched = client.get("/api/events?event_class=unexpected").json()
    assert {e["event_class"] for e in sched} == {"unexpected"}
    imp = _v(list[ImpactEstimate], client.get(f"/api/events/{evs[0].event_id}/impact").json())
    assert imp and all(i.event_id == evs[0].event_id for i in imp)


def test_analysts_fundamentals_macro(client):
    an = _v(list[AnalystObservation], client.get("/api/analysts?security_id=JPM").json())
    assert an and {a.security_id for a in an} == {"JPM"}
    fu = _v(list[Observation],
            client.get("/api/fundamentals?security_id=JPM&metric_id=eps_surprise_pct").json())
    assert fu and all(o.security_id == "JPM" for o in fu)
    ma = _v(list[Observation],
            client.get("/api/macro?metric_id=DFF&metric_id=DGS10&start=2024-12-01").json())
    assert {o.metric_id for o in ma} == {"DFF", "DGS10"}
    assert all(o.security_id is None for o in ma)


def test_forecast(client):
    r = client.post("/api/forecast", json={"security_ids": ["JPM", "BAC"], "horizons": ["short"]})
    assert r.status_code == 200
    run = _v(ForecastRun, r.json())
    assert run.run_id == r.headers["x-run-id"]
    assert len(run.forecasts) == 2


def test_forecast_body_as_of_date(client):
    r = client.post("/api/forecast", json={"security_ids": ["JPM"], "as_of": "2023-03-10"})
    assert r.status_code == 200
    assert _v(ForecastRun, r.json()).as_of == as_of_for_date(datetime(2023, 3, 10).date())


def test_portfolio_evaluate_and_optimize(client):
    for path in ("/api/portfolio/evaluate", "/api/portfolio/optimize"):
        r = client.post(path, json={"portfolio": PORTFOLIO})
        assert r.status_code == 200, r.text
        ev = _v(PortfolioEvaluation, r.json())
        assert ev.feasible and ev.run_id == r.headers["x-run-id"] and ev.run_id


def test_portfolio_infeasible_is_200_with_issues(client):
    bad = {**PORTFOLIO, "holdings": [{"security_id": "JPM", "weight": 0.5}]}
    ev = _v(PortfolioEvaluation, client.post("/api/portfolio/evaluate", json={"portfolio": bad}).json())
    assert not ev.feasible and ev.issues[0].code == "weights_sum"


def test_alerts_flow(client):
    rules = _v(list[AlertRule], client.get("/api/alerts/rules").json())
    assert "concentration" in {r.rule_id for r in rules}
    r = client.post("/api/alerts/evaluate", json={"portfolio": PORTFOLIO, "as_of": "2024-06-03"})
    assert r.status_code == 200
    alerts = _v(list[Alert], r.json())
    assert len(alerts) == 1 and alerts[0].run_id == r.headers["x-run-id"]
    aid = alerts[0].alert_id
    assert [a["alert_id"] for a in client.get("/api/alerts?status=new").json()] == [aid]
    t = client.post(f"/api/alerts/{aid}/transition", json={"to_status": "acknowledged"})
    assert _v(Alert, t.json()).status.value == "acknowledged"
    assert client.get("/api/alerts?status=new").json() == []
    client.post(f"/api/alerts/{aid}/transition", json={"to_status": "resolved"})
    bad = client.post(f"/api/alerts/{aid}/transition", json={"to_status": "new"})
    assert bad.status_code == 422 and bad.json()["detail"]["code"] == "invalid_transition"


def test_alerts_unknown_rule_is_422(client):
    r = client.post("/api/alerts/evaluate", json={"portfolio": PORTFOLIO, "rule_ids": ["nope"]})
    assert r.status_code == 422 and r.json()["detail"]["field"] == "rule_ids"


def test_replay(client):
    body = {"portfolio": PORTFOLIO, "start": "2023-03-01", "end": "2023-03-31",
            "step_trading_days": 5}
    r = client.post("/api/replay", json=body)
    assert r.status_code == 200, r.text
    res = _v(ReplayResult, r.json())
    assert res.frames and res.run_id == r.headers["x-run-id"]
    bad = client.post("/api/replay", json={**body, "start": "2023-04-01"})
    assert bad.status_code == 422 and bad.json()["detail"]["field"] == "start"


# ---- errors -------------------------------------------------------------------------------
@pytest.mark.parametrize(
    "method,path,body",
    [
        ("get", "/api/prices/NOPE", None),
        ("get", "/api/peers/NOPE", None),
        ("get", "/api/events/nope/impact", None),
        ("get", "/api/analysts?security_id=NOPE", None),
        ("post", "/api/alerts/nope/transition", {"to_status": "acknowledged"}),
        ("get", "/api/runs/nope", None),
        ("post", "/api/runs/nope/reproduce", None),
        ("get", "/api/no-such-route", None),
    ],
)
def test_404(client, method, path, body):
    r = getattr(client, method)(path, **({"json": body} if body else {}))
    assert r.status_code == 404
    d = r.json()["detail"]
    assert set(d) == {"code", "message", "field"} and d["code"] == "not_found"


def test_event_not_yet_known_is_404(client):
    # The 2023-03-13 stress event was not knowable as of 2022-06-01.
    r = client.get("/api/events/stress-2023-03-13/impact?as_of=2022-06-01")
    assert r.status_code == 404


@pytest.mark.parametrize(
    "method,path,body,field",
    [
        ("post", "/api/forecast", {"security_ids": ["NOPE"]}, "security_ids"),
        ("post", "/api/forecast", {"security_ids": []}, "security_ids"),
        ("post", "/api/forecast", {"security_ids": ["JPM"], "as_of": "2024-01-02T10:00:00"},
         "as_of"),
        ("post", "/api/forecast", {"security_ids": ["JPM"], "bogus": 1}, "bogus"),
        ("post", "/api/portfolio/evaluate", {"portfolio": {"total_value": -1, "holdings": []}},
         "portfolio.total_value"),
        ("get", "/api/prices/JPM?as_of=2024-01-02T10:00:00", None, "as_of"),
        ("get", "/api/prices/JPM?as_of=yesterday", None, "as_of"),
        ("get", "/api/prices/JPM?start=2024-02-01&end=2024-01-01", None, "start"),
        ("get", "/api/alerts?status=bogus", None, "status"),
        ("get", "/api/runs?limit=0", None, "limit"),
    ],
)
def test_422(client, method, path, body, field):
    r = getattr(client, method)(path, **({"json": body} if body is not None else {}))
    assert r.status_code == 422, r.text
    d = r.json()["detail"]
    assert set(d) == {"code", "message", "field"}
    assert d["field"] == field


def test_unavailable_services_is_503(tmp_path):
    def boom():
        raise RuntimeError("engine X missing")

    c = TestClient(create_app(state_dir=tmp_path, services_factory=boom))
    assert c.get("/api/health").status_code == 200
    r = c.get("/api/meta")
    assert r.status_code == 503
    assert r.json()["detail"]["code"] == "services_unavailable"
    assert "engine X missing" in r.json()["detail"]["message"]


def test_cors(client):
    r = client.options("/api/meta", headers={"Origin": "http://localhost:5173",
                                              "Access-Control-Request-Method": "GET"})
    assert r.headers["access-control-allow-origin"] == "http://localhost:5173"
    r = client.options("/api/meta", headers={"Origin": "http://evil.example",
                                              "Access-Control-Request-Method": "GET"})
    assert "access-control-allow-origin" not in r.headers


# ---- settings -----------------------------------------------------------------------------
def test_settings_defaults_from_yaml(client):
    s = _v(Settings, client.get("/api/settings").json())
    assert {h.value: d for h, d in s.horizon_days.items()} == {"short": 20, "medium": 126, "long": 504}
    assert s.constraints.max_position_weight == 0.40
    assert s.default_portfolio.portfolio_id == "demo"
    assert len(s.alert_rules) == 5


def test_settings_round_trip_persists_and_feeds_alerts(store, tmp_path):
    app = create_app(fake_services(store, []), state_dir=tmp_path)
    c = TestClient(app)
    s = c.get("/api/settings").json()
    s["horizon_days"]["short"] = 10
    s["alert_rules"] = [r for r in s["alert_rules"] if r["rule_id"] == "concentration"]
    s["alert_rules"][0]["threshold"] = 0.9
    r = c.put("/api/settings", json=s)
    assert r.status_code == 200
    assert r.json() == s
    assert (tmp_path / "settings.json").exists()
    assert [x["threshold"] for x in c.get("/api/alerts/rules").json()] == [0.9]
    # Threshold 0.9 means the 50% JPM position no longer triggers.
    assert c.post("/api/alerts/evaluate", json={"portfolio": PORTFOLIO}).json() == []
    # A fresh app over the same state dir reads the saved settings and applies the rules.
    c2 = TestClient(create_app(fake_services(store, []), state_dir=tmp_path))
    assert c2.get("/api/settings").json() == s
    assert [x["threshold"] for x in c2.get("/api/alerts/rules").json()] == [0.9]


@pytest.mark.parametrize(
    "mutate,field",
    [
        (lambda s: s["horizon_days"].pop("long"), "horizon_days"),
        (lambda s: s["alert_rules"].append(dict(s["alert_rules"][0])), "alert_rules"),
        (lambda s: s["default_portfolio"]["holdings"].pop(), "default_portfolio.holdings"),
        (lambda s: s["constraints"].update(long_only=False), "constraints.long_only"),
    ],
)
def test_settings_validation(client, mutate, field):
    s = client.get("/api/settings").json()
    mutate(s)
    r = client.put("/api/settings", json=s)
    assert r.status_code == 422 and r.json()["detail"]["field"] == field


def test_default_as_of_is_latest(client, store):
    ps = _v(PriceSeries, client.get("/api/prices/JPM?start=2024-12-01").json())
    assert ps.as_of == store.latest_as_of().astimezone(timezone.utc)

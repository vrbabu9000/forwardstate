"""BRD acceptance checks AC-01..AC-07 (p.12). Workflow functionality, not investment performance."""

from __future__ import annotations

import copy

import pytest

BANKS = ["JPM", "BAC", "C", "MS", "GS"]


# AC-01 ------------------------------------------------------------------------------------
@pytest.mark.parametrize("sid", BANKS)
def test_ac01_any_bank_prices_peers_and_events(client, sid):
    prices = client.get(f"/api/prices/{sid}").json()
    assert len(prices["points"]) > 250
    peers = client.get(f"/api/peers/{sid}").json()
    ids = {s["security_id"] for s in peers["series"]}
    assert set(BANKS) <= ids
    events = client.get("/api/events", params={"security_id": sid}).json()
    assert any(e.get("occurred_at") or e.get("scheduled_at") for e in events)


# AC-02 ------------------------------------------------------------------------------------
def test_ac02_event_classes_analysts_and_assumption_change(client):
    events = client.get("/api/events").json()
    classes = {e["event_class"] for e in events}
    assert {"scheduled", "anticipated", "unexpected"} <= classes
    assert all(e["origin"] in {"real", "derived", "synthetic"} for e in events)
    analysts = client.get("/api/analysts", params={"security_id": "JPM"}).json()
    assert analysts and all(a["origin"] for a in analysts)

    req = {"security_ids": ["JPM"], "horizons": ["medium"], "assumptions": {}}
    base = client.post("/api/forecast", json=req).json()
    req["assumptions"] = {"rate_change_bps": 100}
    shifted = client.post("/api/forecast", json=req).json()

    def base_ret(run):
        sc = run["forecasts"][0]["scenarios"]
        return next(s["projected_return"] for s in sc if s["scenario"] == "base")

    assert base_ret(shifted) != base_ret(base)


# AC-03 ------------------------------------------------------------------------------------
def test_ac03_three_scenarios_per_horizon(client):
    run = client.post("/api/forecast", json={"security_ids": BANKS,
                                             "horizons": ["short", "medium", "long"]}).json()
    assert len(run["forecasts"]) == 15
    for f in run["forecasts"]:
        if f["status"] == "unavailable":
            assert f["status_reason"]
            continue
        by = {s["scenario"]: s for s in f["scenarios"]}
        assert set(by) == {"optimistic", "base", "pessimistic"}
        assert by["optimistic"]["projected_price"] >= by["base"]["projected_price"] >= by["pessimistic"]["projected_price"]
        assert by["base"]["interval_low"] <= by["base"]["projected_price"] <= by["base"]["interval_high"]


# AC-04 ------------------------------------------------------------------------------------
def test_ac04_valid_portfolio_compared_with_candidates(client, demo_portfolio):
    ev = client.post("/api/portfolio/optimize", json={"portfolio": demo_portfolio}).json()
    assert ev["feasible"] is True
    assert ev["current"] and ev["candidates"]
    for cand in ev["candidates"]:
        assert abs(sum(cand["weights"].values()) - 1) < 1e-6


def test_ac04_infeasible_constraints_rejected(client, demo_portfolio):
    bad = copy.deepcopy(demo_portfolio)
    bad["holdings"][0]["weight"] -= 0.1  # weights sum to 0.9
    res = client.post("/api/portfolio/evaluate", json={"portfolio": bad})
    body = res.json()
    if res.status_code == 200:
        assert body["feasible"] is False and body["issues"]
        assert not body["candidates"]
    else:
        assert res.status_code == 422


# AC-05 ------------------------------------------------------------------------------------
def test_ac05_replayed_shock_raises_explained_alert(client, demo_portfolio):
    res = client.post("/api/replay", json={"portfolio": demo_portfolio, "start": "2023-03-01",
                                           "end": "2023-03-31", "step_trading_days": 1}).json()
    assert res["alerts"], "the synthetic 2023-03-13 stress should trigger at least one alert"
    a = res["alerts"][0]
    assert a["evidence"]
    assert a["projected_loss"] is not None
    labels = " ".join(o["label"].lower() for o in a["alternatives"])
    assert "hold" in labels and "cash" in labels
    assert "does not trade" in a["decision_boundary"]


# AC-06 ------------------------------------------------------------------------------------
def test_ac06_trace_and_reproduce_with_no_trade_capability(client):
    run = client.post("/api/forecast", json={"security_ids": ["JPM"], "horizons": ["short"]}).json()
    rec = client.get(f"/api/runs/{run['run_id']}").json()
    assert rec["model_version"] and rec["input_hash"] and rec["as_of"]
    rep = client.post(f"/api/runs/{run['run_id']}/reproduce").json()
    assert rep["match"] is True

    paths = " ".join(r for r in client.get("/openapi.json").json()["paths"]).lower()
    for word in ("order", "trade", "execute", "broker", "buy", "sell"):
        assert word not in paths


# AC-07 ------------------------------------------------------------------------------------
def test_ac07_fixture_sector_plugs_in_without_shared_changes():
    from forwardstate.contracts import EventClass, Security, SecurityRole
    from forwardstate.industries import get_sector, register_sector, registered_sectors

    class DummySector:
        sector_id = "dummy_fixture"

        def universe(self):
            return [Security(security_id="AAA", ticker="AAA", name="Fixture Co", sector=self.sector_id,
                             role=SecurityRole.FOCAL)]

        def benchmarks(self):
            return []

        def event_taxonomy(self):
            return {EventClass.SCHEDULED: ["fixture_report"]}

        def indicators(self):
            return ["fixture_metric"]

        def exposure(self, event, security_ids):
            return dict.fromkeys(security_ids, 1.0)

    register_sector(DummySector())
    assert "dummy_fixture" in registered_sectors()
    assert get_sector("financials").sector_id == "financials"


def test_ac07_freshness_and_failure_states(client):
    sources = client.get("/api/sources").json()
    assert sources and all(s["health"] in {"fresh", "stale", "missing", "error", "disabled"} for s in sources)
    meta = client.get("/api/meta").json()
    assert meta["data_origin"] == "synthetic" and meta["mode"] == "replay"

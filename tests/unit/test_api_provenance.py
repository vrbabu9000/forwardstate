"""Run provenance and reproduction (AC-06)."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from pydantic import TypeAdapter

from forwardstate.api.app import create_app
from forwardstate.api.compute import REQUEST_TYPES
from forwardstate.api.fakes import fake_services
from forwardstate.api.runs import RunRegistry, output_hash, strip_volatile
from forwardstate.api.settings_store import default_settings
from forwardstate.contracts import CONTRACT_VERSION, ReproduceResult, RunRecord, stable_hash
from forwardstate.testing import FixtureStore

PORTFOLIO = {
    "total_value": 100000,
    "holdings": [{"security_id": "JPM", "weight": 0.6}, {"security_id": "CASH", "weight": 0.4}],
}

CASES = [
    ("/api/forecast", {"security_ids": ["JPM"], "horizons": ["short"], "as_of": "2024-06-03"},
     "forecast"),
    ("/api/portfolio/evaluate", {"portfolio": PORTFOLIO}, "portfolio"),
    ("/api/portfolio/optimize", {"portfolio": PORTFOLIO}, "optimize"),
    ("/api/alerts/evaluate", {"portfolio": PORTFOLIO, "as_of": "2024-06-03"}, "alerts"),
    ("/api/replay", {"portfolio": PORTFOLIO, "start": "2024-01-02", "end": "2024-01-31"}, "replay"),
]


@pytest.fixture(scope="module")
def store() -> FixtureStore:
    return FixtureStore()


@pytest.fixture()
def client(store, tmp_path) -> TestClient:
    return TestClient(create_app(fake_services(store, default_settings().alert_rules), tmp_path))


@pytest.mark.parametrize("path,body,kind", CASES)
def test_run_recorded_and_reproduces(client, tmp_path, path, body, kind):
    r = client.post(path, json=body)
    assert r.status_code == 200, r.text
    run_id = r.headers["x-run-id"]
    rec = TypeAdapter(RunRecord).validate_python(client.get(f"/api/runs/{run_id}").json())
    assert rec.kind.value == kind
    # The full request (defaults filled in) is stored, so it can be re-run exactly.
    req_type = REQUEST_TYPES[rec.kind]
    stored = req_type.model_validate(rec.request)
    sent = req_type.model_validate({k: v for k, v in body.items() if k != "as_of"})
    assert stored.model_copy(update={"as_of": None} if "as_of" in body else {}) == sent
    assert rec.as_of is not None and rec.data_cutoff is not None
    assert rec.data_cutoff <= rec.as_of
    assert rec.model_version.startswith("fake-")
    assert rec.contract_version == CONTRACT_VERSION
    assert rec.data_origin.value == "synthetic"
    assert rec.output_hash == output_hash(r.json())
    assert rec.source_status and rec.source_status[0]["source_id"] == "synthetic"

    rep = client.post(f"/api/runs/{run_id}/reproduce")
    assert rep.status_code == 200
    res = TypeAdapter(ReproduceResult).validate_python(rep.json())
    assert res.match is True, res.note
    assert res.run_id == run_id and res.reproduced_run_id != run_id
    assert res.original_output_hash == res.reproduced_output_hash == rec.output_hash
    # The reproduction is itself recorded and traceable.
    again = client.get(f"/api/runs/{res.reproduced_run_id}").json()
    assert again["input_hash"] == rec.input_hash

    # Append-only JSONL on disk.
    lines = (tmp_path / "runs.jsonl").read_text().splitlines()
    assert [json.loads(x)["run_id"] for x in lines][-2:] == [run_id, res.reproduced_run_id]


def test_config_hash_matches_settings(client):
    from forwardstate.contracts import Settings

    r = client.post("/api/portfolio/evaluate", json={"portfolio": PORTFOLIO})
    rec = client.get(f"/api/runs/{r.headers['x-run-id']}").json()
    settings = Settings.model_validate(client.get("/api/settings").json())
    assert rec["config_hash"] == stable_hash(settings)


def test_engine_run_id_kept_or_assigned(client):
    f = client.post("/api/forecast", json={"security_ids": ["JPM"]})
    # The fake forecaster sets its own run_id; the API keeps it.
    assert f.json()["run_id"] == f.headers["x-run-id"]
    # The fake portfolio engine returns run_id="" ; the API assigns a uuid4 hex.
    p = client.post("/api/portfolio/evaluate", json={"portfolio": PORTFOLIO})
    rid = p.json()["run_id"]
    assert len(rid) == 32 and int(rid, 16) >= 0


def test_reproduce_notes_settings_change(client):
    r = client.post("/api/alerts/evaluate", json={"portfolio": PORTFOLIO, "as_of": "2024-06-03"})
    run_id = r.headers["x-run-id"]
    s = client.get("/api/settings").json()
    for rule in s["alert_rules"]:
        rule["threshold"] = 0.99
    assert client.put("/api/settings", json=s).status_code == 200
    res = client.post(f"/api/runs/{run_id}/reproduce").json()
    assert res["match"] is False
    assert "Settings changed" in res["note"]


def test_runs_list_filter_and_limit(client):
    for path, body, _ in CASES:
        client.post(path, json=body)
    runs = client.get("/api/runs").json()
    assert [r["kind"] for r in runs] == ["replay", "alerts", "optimize", "portfolio", "forecast"]
    assert [r["kind"] for r in client.get("/api/runs?kind=forecast").json()] == ["forecast"]
    assert len(client.get("/api/runs?limit=2").json()) == 2


def test_registry_reloads_from_disk(client, tmp_path):
    client.post("/api/forecast", json={"security_ids": ["JPM"]})
    reg = RunRegistry(tmp_path)
    assert len(reg) == 1
    rid = reg.list()[0].run_id
    with pytest.raises(ValueError):
        reg.add(reg.get(rid))


def test_strip_volatile_is_recursive_and_keeps_alert_id():
    obj = {"run_id": "x", "created_at": "t", "a": [{"run_id": "y", "alert_id": "k", "v": 1}],
           "reproduced_run_id": "z"}
    assert strip_volatile(obj) == {"a": [{"alert_id": "k", "v": 1}]}

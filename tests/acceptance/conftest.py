"""Acceptance tests (BRD p.12, AC-01..AC-07) through the HTTP API.

They run on the labelled SYNTHETIC fixture with the real engines, so they are deterministic and
need no network. They prove workflow functionality, not investment performance.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from forwardstate.alerts import AlertEngine, load_rules
from forwardstate.api.app import create_app
from forwardstate.api.container import Services
from forwardstate.contracts import DataOrigin
from forwardstate.events import EventEngine
from forwardstate.forecasting import ForecastEngine
from forwardstate.portfolio import PortfolioEngine
from forwardstate.testing import FixtureStore

ROOT = Path(__file__).resolve().parents[2]


def build_fixture_services() -> Services:
    store = FixtureStore()
    events = EventEngine(store, sector="financials")
    forecaster = ForecastEngine(store, events, sector="financials")
    portfolio = PortfolioEngine(store, forecaster)
    alerts = AlertEngine(store, forecaster, events, portfolio, load_rules(ROOT / "configs/risk.example.yaml"))
    return Services(store=store, events=events, forecaster=forecaster, portfolio=portfolio,
                    alerts=alerts, data_origin=DataOrigin.SYNTHETIC, sector="financials")


@pytest.fixture(scope="session")
def client(tmp_path_factory) -> TestClient:
    app = create_app(services=build_fixture_services(), state_dir=tmp_path_factory.mktemp("state"))
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="session")
def demo_portfolio(client) -> dict:
    return client.get("/api/settings").json()["default_portfolio"]

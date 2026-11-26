import importlib
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]

PACKAGES = [
    "forwardstate",
    "forwardstate.ingest",
    "forwardstate.storage",
    "forwardstate.contracts",
    "forwardstate.events",
    "forwardstate.features",
    "forwardstate.forecasting",
    "forwardstate.portfolio",
    "forwardstate.risk",
    "forwardstate.alerts",
    "forwardstate.industries",
    "forwardstate.industries.financials",
]


def test_packages_import():
    for name in PACKAGES:
        assert importlib.import_module(name).__doc__


def test_financials_universe_matches_brd():
    cfg = yaml.safe_load((ROOT / "configs/sectors/financials.yaml").read_text())
    tickers = [s["ticker"] for s in cfg["universe"]]
    assert tickers == ["JPM", "BAC", "C", "MS", "GS"]
    assert cfg["focal"] == "JPM"

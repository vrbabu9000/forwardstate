"""Wiring: which store and which engines the API uses (services.py, Wave 2).

``build_services`` picks the real point-in-time store when it holds data, otherwise the labelled
synthetic ``FixtureStore``. It never fakes an engine: if one is missing, it raises.
"""

from __future__ import annotations

import importlib
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from forwardstate.contracts import AlertRule, DataOrigin, Settings
from forwardstate.services import (
    AlertService,
    EventService,
    ForecastService,
    PointInTimeStore,
    PortfolioService,
    SectorModule,
)

from .settings_store import risk_config_path

log = logging.getLogger("forwardstate.api")

DEFAULT_SECTOR = "financials"


class EngineUnavailableError(RuntimeError):
    """A required engine module is missing or broken. The API will not fake it."""


@dataclass
class Services:
    store: PointInTimeStore
    events: EventService
    forecaster: ForecastService
    portfolio: PortfolioService
    alerts: AlertService
    data_origin: DataOrigin
    sector: SectorModule | Any
    # Builds a fresh AlertService for a new rule set. Used only when ``alerts`` has no
    # ``set_rules`` method. Rebuilding loses the engine's in-memory alert inbox.
    alerts_factory: Callable[[list[AlertRule]], AlertService] | None = field(default=None)

    @property
    def sector_id(self) -> str:
        return str(getattr(self.sector, "sector_id", self.sector or DEFAULT_SECTOR))

    def apply_settings(self, settings: Settings) -> None:
        """Push Settings into the engines: horizon lengths and alert rules (UI-04)."""
        for engine in (self.forecaster, self.portfolio):
            if hasattr(engine, "horizon_days"):
                engine.horizon_days = dict(settings.horizon_days)
        self.apply_alert_rules(settings.alert_rules)

    def apply_alert_rules(self, rules: list[AlertRule]) -> None:
        """Make the alert engine use ``rules`` (from Settings)."""
        setter = getattr(self.alerts, "set_rules", None)
        if callable(setter):
            setter(list(rules))
        elif self.alerts_factory is not None:
            self.alerts = self.alerts_factory(list(rules))
        else:
            raise EngineUnavailableError(
                "The alert engine has no set_rules() and no factory was given; "
                "cannot apply alert rules from settings."
            )


def _import(module: str, attr: str) -> Any:
    try:
        mod = importlib.import_module(module)
    except Exception as e:
        raise EngineUnavailableError(
            f"Cannot import engine module '{module}' ({type(e).__name__}: {e}). "
            "The API does not fake engines; build or fix that module first."
        ) from e
    try:
        return getattr(mod, attr)
    except AttributeError as e:
        raise EngineUnavailableError(f"Module '{module}' has no '{attr}'.") from e


def _store_has_data(store: Any) -> bool:
    try:
        if not store.securities():
            return False
        return store.latest_as_of() is not None
    except Exception as e:  # noqa: BLE001
        log.warning("Real store is present but unreadable: %s: %s", type(e).__name__, e)
        return False


def _db_path(data_dir: Path) -> Path:
    """Map ``data_dir`` to the store file. ``storage.DEFAULT_DB_PATH`` is relative to 'data/'."""
    if data_dir.suffix:  # already a file path
        return data_dir
    try:
        default = Path(importlib.import_module("forwardstate.storage").DEFAULT_DB_PATH)
    except (ImportError, AttributeError):
        return data_dir
    parts = default.parts
    return data_dir.joinpath(*parts[1:]) if parts and parts[0] == "data" else data_dir / default.name


def open_data_store(data_dir: Path) -> tuple[PointInTimeStore, DataOrigin]:
    """The real store when it has data, else the synthetic fixture (with a loud warning)."""
    reason: str
    try:
        open_store = _import("forwardstate.storage", "open_store")
        db_path = _db_path(data_dir)
        store = open_store(db_path)
        if store is not None and _store_has_data(store):
            log.info("Using the real point-in-time store at %s", data_dir)
            return store, DataOrigin.REAL
        reason = f"the store at {db_path} has no data (run 'forwardstate fetch')"
    except EngineUnavailableError as e:
        reason = str(e)
    except Exception as e:  # noqa: BLE001
        reason = f"open_store({data_dir}) failed: {type(e).__name__}: {e}"
    from forwardstate.testing import FixtureStore

    log.warning(
        "USING SYNTHETIC DATA: %s. Every response is labelled data_origin=synthetic. "
        "These are not real market prices.",
        reason,
    )
    return FixtureStore(), DataOrigin.SYNTHETIC


def build_services(
    data_dir: Path = Path("data"),
    sector_id: str = DEFAULT_SECTOR,
    rules: list[AlertRule] | None = None,
    config_dir: Path | None = None,
    state_dir: Path | None = None,
) -> Services:
    """Build the store and the real engines. Raises ``EngineUnavailableError`` if one is missing.

    Engines take the sector *id* (they call ``get_sector`` themselves). When ``state_dir`` is
    given, the alert inbox is persisted to ``state_dir/alerts.json``, so rebuilding the alert
    engine after a settings change keeps existing alerts and their status.
    """
    store, origin = open_data_store(Path(data_dir))

    get_sector = _import("forwardstate.industries", "get_sector")
    try:
        sector = get_sector(sector_id)
    except Exception as e:
        raise EngineUnavailableError(f"Sector module '{sector_id}' is not available: {e}") from e

    EventEngine = _import("forwardstate.events", "EventEngine")
    ForecastEngine = _import("forwardstate.forecasting", "ForecastEngine")
    PortfolioEngine = _import("forwardstate.portfolio", "PortfolioEngine")
    AlertEngine = _import("forwardstate.alerts", "AlertEngine")

    if rules is None:
        load_rules = _import("forwardstate.alerts", "load_rules")
        rules = load_rules(risk_config_path(config_dir))

    events = EventEngine(store, sector_id)
    forecaster = ForecastEngine(store, events, sector_id)
    portfolio = PortfolioEngine(store, forecaster)
    persist = {"persist_path": Path(state_dir) / "alerts.json"} if state_dir else {}

    def alerts_factory(rs: list[AlertRule]) -> AlertService:
        return AlertEngine(store, forecaster, events, portfolio, rs, **persist)

    return Services(
        store=store,
        events=events,
        forecaster=forecaster,
        portfolio=portfolio,
        alerts=alerts_factory(list(rules)),
        data_origin=origin,
        sector=sector,
        alerts_factory=alerts_factory,
    )

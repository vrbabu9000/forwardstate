"""Per-app state: lazily built services, settings and the run registry."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Annotated

from fastapi import Depends, Request

from forwardstate.pit import ensure_utc

from .container import Services, build_services
from .errors import ApiError
from .runs import RunRegistry
from .settings_store import SettingsStore

log = logging.getLogger("forwardstate.api")


class AppContext:
    def __init__(
        self,
        services: Services | None,
        state_dir: Path,
        config_dir: Path | None = None,
        data_dir: Path = Path("data"),
        services_factory: Callable[[], Services] | None = None,
    ) -> None:
        self._services = services
        self._factory = services_factory or (
            lambda: build_services(data_dir, config_dir=config_dir, state_dir=state_dir)
        )
        self.state_dir = Path(state_dir)
        self.settings = SettingsStore(self.state_dir, config_dir)
        self.runs = RunRegistry(self.state_dir)
        self._lock = threading.Lock()
        self._rules_applied = False

    def services(self) -> Services:
        """Build services on first use. Failures become a 503 with the real reason."""
        if self._services is not None and self._rules_applied:
            return self._services
        with self._lock:
            if self._services is None:
                try:
                    self._services = self._factory()
                except Exception as e:
                    log.exception("Could not build services")
                    raise ApiError(503, "services_unavailable", f"{type(e).__name__}: {e}") from e
            if not self._rules_applied:
                try:
                    self._services.apply_settings(self.settings.get())
                except Exception as e:
                    raise ApiError(
                        503, "services_unavailable", f"Could not apply alert rules: {e}"
                    ) from e
                self._rules_applied = True
            return self._services

    def latest_as_of(self) -> datetime:
        store = self.services().store
        try:
            latest = store.latest_as_of()
        except Exception as e:
            raise ApiError(503, "data_not_loaded", f"No data is loaded: {e}") from e
        if latest is None:
            raise ApiError(503, "data_not_loaded", "No data is loaded.")
        return ensure_utc(latest)

    def resolve_as_of(self, as_of: datetime | None) -> datetime:
        return ensure_utc(as_of) if as_of is not None else self.latest_as_of()


def get_ctx(request: Request) -> AppContext:
    return request.app.state.ctx


Ctx = Annotated[AppContext, Depends(get_ctx)]

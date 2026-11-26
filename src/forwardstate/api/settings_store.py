"""User settings (UI-04), persisted to ``state_dir/settings.json``.

Defaults come from ``configs/risk.yaml`` (or ``risk.example.yaml``), ``configs/portfolio.yaml``
(or ``portfolio.example.yaml``) and ``DEFAULT_HORIZON_DAYS``. Example values are illustrative and
not approved (BRD p.15).
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any

import yaml

from forwardstate.contracts import (
    DEFAULT_HORIZON_DAYS,
    Constraints,
    Horizon,
    Portfolio,
    ScenarioAssumptions,
    Settings,
)

from .errors import invalid

DEFAULT_CONFIG_DIR = Path(__file__).resolve().parents[3] / "configs"


def _config_file(config_dir: Path, stem: str) -> Path:
    for name in (f"{stem}.yaml", f"{stem}.example.yaml"):
        p = config_dir / name
        if p.exists():
            return p
    raise FileNotFoundError(f"No {stem}.yaml or {stem}.example.yaml in {config_dir}")


def risk_config_path(config_dir: Path | None = None) -> Path:
    return _config_file(Path(config_dir or DEFAULT_CONFIG_DIR), "risk")


def _load_yaml(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    if not isinstance(data, dict):
        raise TypeError(f"{path} must contain a mapping at the top level")
    return data


def default_settings(config_dir: Path | None = None) -> Settings:
    config_dir = Path(config_dir or DEFAULT_CONFIG_DIR)
    risk = _load_yaml(_config_file(config_dir, "risk"))
    pf = _load_yaml(_config_file(config_dir, "portfolio"))
    horizon_days = dict(DEFAULT_HORIZON_DAYS)
    for k, v in (risk.get("horizon_days") or {}).items():
        horizon_days[Horizon(k)] = int(v)
    constraints = Constraints(**(risk.get("constraints") or {}))
    pf.setdefault("constraints", constraints.model_dump())
    return Settings(
        horizon_days=horizon_days,
        constraints=constraints,
        assumptions=ScenarioAssumptions(**(risk.get("assumptions") or {})),
        alert_rules=risk.get("alert_rules") or [],
        default_portfolio=Portfolio(**pf),
    )


def check_settings(s: Settings) -> None:
    """Rules beyond the pydantic contract. Raises a 422 ApiError."""
    missing = [h.value for h in Horizon if h not in s.horizon_days]
    if missing:
        raise invalid(f"horizon_days is missing: {', '.join(missing)}", "horizon_days")
    for h, d in s.horizon_days.items():
        if d < 1:
            raise invalid(f"horizon_days.{h.value} must be at least 1 trading day", "horizon_days")
    ids = [r.rule_id for r in s.alert_rules]
    dupes = sorted({i for i in ids if ids.count(i) > 1})
    if dupes:
        raise invalid(f"Duplicate alert rule_id: {', '.join(dupes)}", "alert_rules")
    total = sum(h.weight for h in s.default_portfolio.holdings)
    if abs(total - 1.0) > 1e-6:
        raise invalid(
            f"default_portfolio weights sum to {total:.4f}; they must sum to 1.0",
            "default_portfolio.holdings",
        )


class SettingsStore:
    def __init__(self, state_dir: Path, config_dir: Path | None = None) -> None:
        self.path = Path(state_dir) / "settings.json"
        self.config_dir = Path(config_dir or DEFAULT_CONFIG_DIR)
        self._lock = threading.Lock()
        self._cached: Settings | None = None

    def get(self) -> Settings:
        with self._lock:
            if self._cached is None:
                if self.path.exists():
                    self._cached = Settings.model_validate_json(self.path.read_text("utf-8"))
                else:
                    self._cached = default_settings(self.config_dir)
            return self._cached

    def put(self, settings: Settings) -> Settings:
        check_settings(settings)
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".json.tmp")
            tmp.write_text(
                json.dumps(settings.model_dump(mode="json"), indent=2, sort_keys=True), "utf-8"
            )
            os.replace(tmp, self.path)
            self._cached = settings
        return settings

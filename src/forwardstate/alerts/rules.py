"""Load alert rules from a YAML config (fields = contracts.AlertRule)."""

from __future__ import annotations

from pathlib import Path

import yaml

from forwardstate.contracts import AlertRule

DEFAULT_RULES_PATH = "configs/risk.example.yaml"
_REPO_ROOT = Path(__file__).resolve().parents[3]


def _resolve(path: str | Path) -> Path:
    p = Path(path)
    if p.exists() or p.is_absolute():
        return p
    return _REPO_ROOT / p


def load_rules(path: str | Path = DEFAULT_RULES_PATH) -> list[AlertRule]:
    """Read ``alert_rules`` from the config. Relative paths fall back to the repo root."""
    data = yaml.safe_load(_resolve(path).read_text()) or {}
    return [AlertRule.model_validate(r) for r in data.get("alert_rules", [])]

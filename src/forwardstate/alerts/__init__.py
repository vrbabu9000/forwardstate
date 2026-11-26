"""Alert rules, lifecycle and explainable alert content. Notifies only; never executes trades (BRD layer 6, RISK-03..05)."""

from .engine import MODEL_VERSION, AlertEngine
from .rules import DEFAULT_RULES_PATH, load_rules

__all__ = ["DEFAULT_RULES_PATH", "MODEL_VERSION", "AlertEngine", "load_rules"]

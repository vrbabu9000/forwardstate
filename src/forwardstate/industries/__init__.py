"""Industry plug-in modules: peer universe, event taxonomy, indicators, exposure mapping (BRD p.11).

A sector registers itself with ``register_sector``; shared engines look it up with
``get_sector``. Adding a sector must not require changes to shared portfolio or alert logic
(AC-07).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from forwardstate.services import SectorModule

_REGISTRY: dict[str, SectorModule] = {}


def register_sector(module: SectorModule) -> SectorModule:
    _REGISTRY[module.sector_id] = module
    return module


def get_sector(sector_id: str) -> SectorModule:
    if sector_id not in _REGISTRY and sector_id == "financials":
        from . import financials  # noqa: F401  (registers on import)
    try:
        return _REGISTRY[sector_id]
    except KeyError:
        raise KeyError(f"Unknown sector '{sector_id}'. Registered: {sorted(_REGISTRY)}") from None


def registered_sectors() -> list[str]:
    return sorted(_REGISTRY)

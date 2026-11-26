"""Financials sector module (MVP): JPM focal, BAC, C, MS, GS peers.

Reads ``configs/sectors/financials.yaml`` and registers itself with the sector registry on
import. Implements ``forwardstate.services.SectorModule``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

from forwardstate.contracts import Event, EventClass, EventScope, Security, SecurityRole
from forwardstate.industries import register_sector

CONFIG_PATH = Path(__file__).resolve().parents[4] / "configs" / "sectors" / "financials.yaml"

# Used only when the YAML file is not present (e.g. an installed wheel without the repo).
_FALLBACK_CONFIG: dict[str, Any] = {
    "sector": "financials",
    "focal": "JPM",
    "universe": [
        {"ticker": "JPM", "name": "JPMorgan Chase", "role": "focal"},
        {"ticker": "BAC", "name": "Bank of America", "role": "peer"},
        {"ticker": "C", "name": "Citigroup", "role": "peer"},
        {"ticker": "MS", "name": "Morgan Stanley", "role": "peer"},
        {"ticker": "GS", "name": "Goldman Sachs", "role": "peer"},
    ],
    "benchmarks": [
        {"ticker": "SPY", "name": "SPDR S&P 500 ETF", "role": "market"},
        {"ticker": "XLF", "name": "Financial Select Sector SPDR", "role": "sector"},
    ],
    "defensive_assets": [{"ticker": "CASH", "name": "Cash / liquid equivalents"}],
    "indicators": [],
    "event_classes": {},
}

# Subtypes the engines rely on. Merged with the YAML lists (YAML order first, then these).
REQUIRED_TAXONOMY: dict[EventClass, list[str]] = {
    EventClass.SCHEDULED: ["quarterly_results", "fomc_meeting", "filing_10q", "filing_10k"],
    EventClass.ANTICIPATED: ["rate_change", "regulatory_development"],
    EventClass.UNEXPECTED: ["price_shock", "filing_8k", "sector_stress", "breaking_news"],
}

PEER_TRANSMISSION_WEIGHT = 0.3  # firm-scope event: weight on each peer bank
BETA_CLIP = (0.0, 1.5)  # market-scope event: beta to SPY is clipped to this range ...
BETA_NORMALISER = 1.5  # ... then divided by this, so weights stay in 0..1
MIN_BETA_OBS = 60  # fewer joint observations than this -> weight falls back to 1.0
BETA_WINDOW = 252  # trailing trading days used for the market beta


def load_config(path: Path = CONFIG_PATH) -> dict[str, Any]:
    if path.exists():
        with path.open() as fh:
            return yaml.safe_load(fh)
    return dict(_FALLBACK_CONFIG)


class FinancialsModule:
    """Peer universe, event taxonomy, indicators and exposure mapping for US banks."""

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config = config or load_config()
        self.sector_id: str = self.config.get("sector", "financials")
        self.focal_id: str = self.config.get("focal", "JPM")
        self.market_benchmark_id = "SPY"
        self.sector_benchmark_id = "XLF"

    # ---- SectorModule ------------------------------------------------------------------
    def universe(self) -> list[Security]:
        out = []
        for row in self.config.get("universe", []):
            role = SecurityRole(row.get("role", "peer"))
            if role not in (SecurityRole.FOCAL, SecurityRole.PEER):
                continue
            out.append(
                Security(security_id=row["ticker"], ticker=row["ticker"], name=row["name"],
                         sector=self.sector_id, role=role)
            )
        return out

    def benchmarks(self) -> list[Security]:
        return [
            Security(security_id=row["ticker"], ticker=row["ticker"], name=row["name"],
                     sector=self.sector_id, role=SecurityRole.BENCHMARK, investable=False)
            for row in self.config.get("benchmarks", [])
        ]

    def defensive_assets(self) -> list[Security]:
        return [
            Security(security_id=row["ticker"], ticker=row["ticker"], name=row["name"],
                     sector=self.sector_id, role=SecurityRole.DEFENSIVE)
            for row in self.config.get("defensive_assets", [])
        ]

    def universe_ids(self) -> list[str]:
        return [s.security_id for s in self.universe()]

    def event_taxonomy(self) -> dict[EventClass, list[str]]:
        cfg = self.config.get("event_classes", {}) or {}
        out: dict[EventClass, list[str]] = {}
        for cls in EventClass:
            items = list(cfg.get(cls.value, []) or [])
            for sub in REQUIRED_TAXONOMY.get(cls, []):
                if sub not in items:
                    items.append(sub)
            out[cls] = items
        return out

    def classify(self, subtype: str) -> EventClass | None:
        """Event class for a subtype key, or None when it is not in the taxonomy."""
        for cls, subs in self.event_taxonomy().items():
            if subtype in subs:
                return cls
        return None

    def indicators(self) -> list[str]:
        return list(self.config.get("indicators", []) or [])

    def exposure(
        self, event: Event, security_ids: list[str], returns: pd.DataFrame | None = None
    ) -> dict[str, float]:
        """Sensitivity weight (0..1) of each security to ``event``.

        - firm scope: 1.0 for the affected firm(s), 0.3 for every other bank (peer transmission);
        - sector scope: 1.0 for every bank;
        - market scope: beta to SPY over the trailing 252 days of ``returns`` (a wide daily
          return frame the caller has already cut to its as-of time), clipped to 0..1.5 and
          divided by 1.5. Falls back to 1.0 when there are fewer than 60 joint observations or
          no ``returns`` are given.
        Non-bank ids (benchmarks, CASH) get 0.0.
        """
        banks = set(self.universe_ids())
        affected = set(event.affected_security_ids)
        out: dict[str, float] = {}
        for sid in security_ids:
            if sid not in banks:
                out[sid] = 0.0
            elif event.scope == EventScope.FIRM:
                out[sid] = 1.0 if sid in affected else PEER_TRANSMISSION_WEIGHT
            elif event.scope == EventScope.SECTOR:
                out[sid] = 1.0
            else:
                out[sid] = self._market_weight(sid, returns)
        return out

    def _market_weight(self, sid: str, returns: pd.DataFrame | None) -> float:
        mkt = self.market_benchmark_id
        if returns is None or sid not in returns.columns or mkt not in returns.columns:
            return 1.0
        joint = returns[[sid, mkt]].dropna().iloc[-BETA_WINDOW:]
        if len(joint) < MIN_BETA_OBS:
            return 1.0
        x = joint[mkt].to_numpy()
        y = joint[sid].to_numpy()
        vx = float(np.var(x, ddof=1))
        if vx <= 0:
            return 1.0
        beta = float(np.cov(x, y, ddof=1)[0, 1] / vx)
        beta = min(max(beta, BETA_CLIP[0]), BETA_CLIP[1])
        return round(beta / BETA_NORMALISER, 6)


MODULE = register_sector(FinancialsModule())

__all__ = ["MODULE", "FinancialsModule", "load_config"]

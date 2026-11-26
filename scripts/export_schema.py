"""Export JSON Schemas of all API contracts to web/src/api/contracts.schema.json.

The frontend generates TypeScript types from this file (see web/README.md).
Run: python scripts/export_schema.py
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic.json_schema import models_json_schema

from forwardstate import contracts as c

MODELS = [
    c.Meta, c.SourceStatus, c.Security, c.PriceSeries, c.PeerComparison, c.Event, c.ImpactEstimate,
    c.AnalystObservation, c.Observation, c.ForecastRequest, c.ForecastRun, c.PortfolioRequest,
    c.PortfolioEvaluation, c.AlertsRequest, c.Alert, c.AlertRule, c.TransitionRequest,
    c.ReplayRequest, c.ReplayResult, c.Settings, c.RunRecord, c.ReproduceResult,
]


def main() -> None:
    _, schema = models_json_schema([(m, "serialization") for m in MODELS],
                                   title="ForwardState contracts " + c.CONTRACT_VERSION)
    out = Path(__file__).resolve().parents[1] / "web" / "src" / "api" / "contracts.schema.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(schema, indent=2, sort_keys=True) + "\n")
    print(f"wrote {out} ({len(schema.get('$defs', {}))} definitions)")


if __name__ == "__main__":
    main()

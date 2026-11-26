# ForwardState HTTP API (contract v1.0.0)

The backend (`src/forwardstate/api/`) and the frontend (`web/`) both build against this file.
Every body is a pydantic model from [`forwardstate.contracts`](../src/forwardstate/contracts/).
JSON Schemas for these models are in
[web/src/api/contracts.schema.json](../web/src/api/contracts.schema.json). To regenerate them, run
`python scripts/export_schema.py`.

## Shared conventions

- **Path prefix:** every route starts with `/api`, and JSON field names are snake_case.
- **Datetimes:** ISO 8601 in UTC. Dates are `YYYY-MM-DD`.
- **`as_of`:** an optional query or body field (a UTC datetime, or a date meaning 23:59 New York
  time that day). When omitted, it defaults to `store.latest_as_of()`. Every response reflects
  only the data available as of that time.
- **Errors:** errors return `{"detail": {"code": str, "message": str, "field": str|null}}`.
  - **404:** unknown id.
  - **422:** invalid input, including infeasible constraints when the call can't return a
    `PortfolioEvaluation` with `feasible=false`.
  - **503:** data not loaded.
- **No silent fallback:** missing data returns `status: "unavailable"` in the body. It never
  returns made-up numbers.
- **No trading:** there are no routes that trade, place orders, connect a broker or move money.

## Routes

| Method & path | Request | Response | Used by |
|---|---|---|---|
| GET `/api/health` | — | `{"status": "ok"}` | ops |
| GET `/api/meta` | — | `Meta` | header banner (mode, origin, disclaimer) |
| GET `/api/sources` | — | `list[SourceStatus]` | freshness indicators, Settings |
| GET `/api/securities?sector=financials` | — | `list[Security]` | selectors |
| GET `/api/prices/{security_id}?start&end&as_of` | — | `PriceSeries` | UI-01 price chart |
| GET `/api/peers/{security_id}?start&end&as_of` | — | `PeerComparison` (focal + 4 peers + XLF, rebased to 100) | UI-01 peer chart |
| GET `/api/events?security_id&event_class&start&end&as_of` | — | `list[Event]` | UI-01 markers, UI-03 |
| GET `/api/events/{event_id}/impact?as_of` | — | `list[ImpactEstimate]` | UI-03 event detail |
| GET `/api/analysts?security_id&as_of` | — | `list[AnalystObservation]` | UI-01 analyst panel |
| GET `/api/fundamentals?security_id&metric_id&as_of` | — | `list[Observation]` | UI-01 fundamentals |
| GET `/api/macro?metric_id=DFF&metric_id=DGS10&start&as_of` | — | `list[Observation]` | UI-01 macro panel |
| POST `/api/forecast` | `ForecastRequest` | `ForecastRun` | UI-01 scenarios |
| POST `/api/portfolio/evaluate` | `PortfolioRequest` | `PortfolioEvaluation` | UI-02 |
| POST `/api/portfolio/optimize` | `PortfolioRequest` | `PortfolioEvaluation` | UI-02 candidates |
| GET `/api/alerts/rules` | — | `list[AlertRule]` | UI-03, UI-04 |
| POST `/api/alerts/evaluate` | `AlertsRequest` | `list[Alert]` | UI-03 |
| GET `/api/alerts?status=` | — | `list[Alert]` | UI-03 inbox |
| POST `/api/alerts/{alert_id}/transition` | `TransitionRequest` | `Alert` | UI-03 acknowledge/resolve |
| POST `/api/replay` | `ReplayRequest` | `ReplayResult` | UI-03 replay |
| GET `/api/settings` | — | `Settings` | UI-04 |
| PUT `/api/settings` | `Settings` | `Settings` | UI-04 |
| GET `/api/runs?kind=&limit=` | — | `list[RunRecord]` | provenance drawer |
| GET `/api/runs/{run_id}` | — | `RunRecord` | provenance drawer |
| POST `/api/runs/{run_id}/reproduce` | — | `ReproduceResult` | provenance drawer (AC-06) |

## Run provenance

Every POST that computes something (`forecast`, `portfolio/*`, `alerts/evaluate`, `replay`)
creates a `RunRecord`. The response's own `run_id` matches the record. The record stores:
- the exact request;
- `config_hash` (settings) and `input_hash` (request + data cutoff + source status);
- `output_hash`;
- `model_version`.

`reproduce` re-runs the stored request with the same `as_of` and compares output hashes. Fields
that legitimately differ are excluded before hashing: `run_id`, `created_at` and
`reproduced_run_id`. `alert_id` is deterministic, so it stays in the hash. The input hash uses
the resolved `as_of`, not the raw request field. Every computing POST also returns its run id in
an `X-Run-Id` response header.

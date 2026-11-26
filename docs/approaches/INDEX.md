# Approaches

Every new approach gets its own file. Copy [_TEMPLATE.md](_TEMPLATE.md). Never delete a dropped one.

| ID | Approach | Area | Date | Status | Replaces | Verdict |
|---|---|---|---|---|---|---|
| [A001](A001-brd-package-layout.md) | One package with a sub-package per BRD layer; sector plug-ins | Code structure | 2026-11-25 | Kept | — | Keep: matches BRD, installs and tests clean |
| [A002](A002-pit-store-and-adapters.md) | Append-only point-in-time DuckDB store + Yahoo/FRED/Fed/EDGAR adapters | Data | 2026-11-26 | Kept | — | Keep: point-in-time by construction; real data loaded |
| [A003](A003-bootstrap-forecasts.md) | Block-bootstrap scenarios with named drift drivers | Forecasting | 2026-11-26 | Kept | — | Keep as baseline; Phase 2 must measure it |
| [A004](A004-portfolio-risk-alerts.md) | Simulated risk, SLSQP candidates, replayable alerts | Portfolio, risk, alerts | 2026-11-26 | Kept | — | Keep; alert thresholds need an approved policy |
| [A005](A005-react-ui-same-origin.md) | React UI built into web/dist and served by the API | UI and workflow | 2026-11-26 | Kept | Streamlit | Keep; one server, typed from contracts |

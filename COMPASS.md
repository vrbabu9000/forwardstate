# Compass v04 · 2026-11-26

## North Star

ForwardState is for <user> *(assumed: an investor or analyst who manages a portfolio and makes
every decision themselves)*. "Done and useful" for the MVP: for JPM and its peers (BAC, C, MS, GS)
plus cash, a replayed market event produces honest scenario forecasts (optimistic / base /
pessimistic), shows the portfolio risk they imply, and raises an explainable alert — using only
data available at that point in time, and never placing a trade.

## Right now

| Phase | Step | Next milestone | Blockers | Time | Top risk |
|---|---|---|---|---|---|
| 1 — Financials MVP | Built and integrated: AC-01..07 pass (tests + browser on real data); review fixes in | You accept/reject Proposed D003, D007, D008, D009; commit | Alert-threshold policy not set (example values noisy); EDGAR off | <time budget / deadline> | Forecasts are uncalibrated until Phase 2 backtesting |

## Phase map

| Phase | Done when | Status |
|---|---|---|
| 0 — Setup | Code scaffold, working rules, docs structure in place | ✅ done |
| 1 — Financials MVP | AC-01..AC-07 pass; React + FastAPI app runs on real Yahoo data | ✅ done (pending your review + commit) |
| 2 — Backtesting & calibration | Forecasts are backtested and calibration is measured | ⚪ not started |
| 3 — Live data | A licensed live feed runs through the same point-in-time pipeline | ⚪ not started |
| 4 — More industries | ~6–7 sectors run as plug-in modules | ⚪ not started |

## Cut list (drop first → last)

1. Dashboard polish (keep plain tables and one price chart).
2. Dashboard peer views (all five banks stay in data and tests — [D006](docs/decisions/D006-cut-list-keeps-five-banks.md)).
3. Optional optimiser (CVXPY); keep simple candidate allocations.
4. Extra alert types; keep one explainable loss alert.

Point-in-time correctness and "no trading" are never cut.

## Change log

| Version | Date | What moved | Decisions changed |
|---|---|---|---|
| v01 | 2026-11-25 | First Compass, from README and BRD v1.0 draft | [D001](docs/decisions/D001-working-rules.md), [D002](docs/decisions/D002-decision-support-only.md), [D003](docs/decisions/D003-python-stack.md) |
| v02 | 2026-11-25 | "Right now" phase fixed to 0 — Setup (matched the phase map); rules reviewed | [D003 v2](docs/decisions/D003-python-stack.md) (evidence added, still Proposed) |
| v03 | 2026-11-25 | Phase 1 started: full build (React + FastAPI, Yahoo data); cut item 2 fixed | [D004](docs/decisions/D004-react-fastapi-ui.md), [D005](docs/decisions/D005-open-data-sources.md), [D006](docs/decisions/D006-cut-list-keeps-five-banks.md), [D007](docs/decisions/D007-pit-handling-yahoo.md) |
| v04 | 2026-11-26 | Phase 1 built by 5 parallel agents + integration; all AC pass on real data; 6 review bugs fixed | [D008](docs/decisions/D008-price-return-forecasts.md), [D009](docs/decisions/D009-serve-ui-from-api.md) (both Proposed) |

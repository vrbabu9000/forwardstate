# Compass v01 · 2026-11-25

## North Star

ForwardState is for <user> *(assumed: an investor or analyst who manages a portfolio and makes
every decision themselves)*. "Done and useful" for the MVP: for JPM and its peers (BAC, C, MS, GS)
plus cash, a replayed market event produces honest scenario forecasts (optimistic / base /
pessimistic), shows the portfolio risk they imply, and raises an explainable alert — using only
data available at that point in time, and never placing a trade.

## Right now

| Phase | Step | Next milestone | Blockers | Time | Top risk |
|---|---|---|---|---|---|
| 1 — Financials MVP | Code scaffold done; project rules set up | Schema + point-in-time fixtures for JPM and peers | None yet | <time budget / deadline> | Fixtures or features leak future data (point-in-time errors) *(guess)* |

## Phase map

| Phase | Done when | Status |
|---|---|---|
| 0 — Setup | Code scaffold, working rules, docs structure in place | 🟡 in progress |
| 1 — Financials MVP | Acceptance checks AC-01..AC-07 from the BRD pass on fixtures | ⚪ not started |
| 2 — Backtesting & calibration | Forecasts are backtested and calibration is measured | ⚪ not started |
| 3 — Live data | A licensed live feed runs through the same point-in-time pipeline | ⚪ not started |
| 4 — More industries | ~6–7 sectors run as plug-in modules | ⚪ not started |

## Cut list (drop first → last)

1. Dashboard polish (keep a plain table view).
2. Peers beyond JPM + one peer.
3. Optional optimiser (CVXPY); keep simple candidate allocations.
4. Extra alert types; keep one explainable loss alert.

Point-in-time correctness and "no trading" are never cut.

## Change log

| Version | Date | What moved | Decisions changed |
|---|---|---|---|
| v01 | 2026-11-25 | First Compass, from README and BRD v1.0 draft | [D001](docs/decisions/D001-working-rules.md), [D002](docs/decisions/D002-decision-support-only.md), [D003](docs/decisions/D003-python-stack.md) |

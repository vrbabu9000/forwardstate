# ForwardState

Event-driven quantitative investment intelligence: probabilistic market forecasting and dynamic
portfolio risk assessment.

ForwardState turns market events and analyst assumptions into stock-level scenario projections,
portfolio-level risk and explainable alerts.

> **Decision support only.** ForwardState does not execute trades, route orders or connect to
> brokers. Every buy, sell or reallocation decision stays with the investor. Its scenarios are
> not guaranteed price targets.

Scope and requirements: [docs/ForwardState_BRD_Technical_Scope.pdf](docs/ForwardState_BRD_Technical_Scope.pdf)
(v1.0 draft).

## Status

Phase 1 (financial-sector MVP) is built. All seven BRD acceptance checks (AC-01..AC-07) pass in
tests and in the running app. The MVP universe is JPM (the focal company), with BAC, C, MS and GS
as peers, plus cash.

The app runs on real open data: Yahoo Finance, FRED and the Fed calendar
([D005](docs/decisions/D005-open-data-sources.md)). It runs in **replay mode**: historical data,
not a live feed.

Forecasts are **not calibrated**. Phase 2 (backtesting) has to measure them before anyone relies
on them. Passing the acceptance checks proves the workflow works, not that it makes money.

Architecture: [PNG](docs/diagrams/png/architecture-v1.png) · [PDF](docs/diagrams/pdf/architecture-v1.pdf)

## Layout

```
src/forwardstate/
  ingest/        source adapters -> normalized records
  storage/       point-in-time store (as-of queries, provenance)
  contracts/     versioned canonical data contracts
  events/        event classification, entity mapping, timeline
  features/      point-in-time feature snapshots
  forecasting/   scenario engine (optimistic / base / pessimistic)
  portfolio/     holdings, constraints, candidate allocations
  risk/          volatility, downside / CVaR, drawdown, concentration
  alerts/        alert rules, lifecycle, explainable content
  industries/    sector plug-ins (financials = MVP)
  api/           FastAPI routes, run registry, settings (serves web/dist too)
  testing/       labelled synthetic dataset + in-memory point-in-time store
web/             React + TypeScript UI (Vite)
scripts/         export_schema.py (contracts -> JSON Schema -> TS types)
configs/         sector and risk settings (example values, not approved)
data/            local store, cache and run state (not committed)
tests/           unit tests + acceptance tests (AC-01..AC-07)
docs/            scope, contracts and evaluation reports
```

## Where things live

| Path | What |
|---|---|
| [CLAUDE.md](CLAUDE.md) | Working rules for this project |
| [COMPASS.md](COMPASS.md) | Project status: phase, step, next milestone, blockers |
| [ACTIVITY-LOG.md](ACTIVITY-LOG.md) | "Pick up here" box and session log |
| [docs/decisions/DECISIONS.md](docs/decisions/DECISIONS.md) | Decision index; one file per decision |
| [docs/approaches/INDEX.md](docs/approaches/INDEX.md) | Approaches tried, kept or dropped |
| [docs/BACKLOG.md](docs/BACKLOG.md) | Tasks with owner, hours and status |
| [docs/roadmap/](docs/roadmap/README.md) | Ideas for later (not current scope) |
| [docs/compass-history/](docs/compass-history/) | Old Compass versions |
| [docs/diagrams/](docs/diagrams/) | Diagram sources, PNG and PDF |

## Setup

You need Python 3.10+ and Node 20+.

```bash
python3 -m venv .venv
```

```bash
.venv/bin/pip install -e ".[dev]"
```

```bash
npm --prefix web install
```

## Run

1. Fetch real data (about 1–2 minutes the first time; cached after that). SEC EDGAR is skipped
   unless you set `FORWARDSTATE_SEC_USER_AGENT`.

```bash
.venv/bin/forwardstate fetch --start 2015-01-01
```

2. Build the UI.

```bash
npm --prefix web run build
```

3. Start the server, then open http://127.0.0.1:8000. If no data was fetched, the app runs on
   the labelled synthetic dataset and says so on every page.

```bash
.venv/bin/forwardstate serve
```

UI development with hot reload (start the API first, then this; it proxies `/api` to port 8000):

```bash
npm --prefix web run dev
```

Offline UI with labelled synthetic mocks only:

```bash
npm --prefix web run dev:mocks
```

## Test

```bash
.venv/bin/pytest
```

```bash
.venv/bin/ruff check .
```

```bash
npm --prefix web run typecheck && npm --prefix web test
```

After changing a contract in `src/forwardstate/contracts/`, regenerate the UI types:

```bash
.venv/bin/python scripts/export_schema.py && npm --prefix web run gen:types
```

## Principles

- **Point-in-time:** a run as of time T uses only records available by T.
- **Reproducible:** model and config versions plus input hashes are stored with every run.
- **Honest uncertainty:** show "unavailable" or "low confidence" rather than invent probabilities.
- **Labelled data:** synthetic fixtures are always marked as synthetic; there is no implied live
  Bloomberg connection.

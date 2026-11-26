# Activity log

## 📌 Pick up here

| | |
|---|---|
| **Last session** | 2026-11-26 |
| **Where we are** | Phase 1 Financials MVP built ([Compass v04](COMPASS.md)). AC-01..07 pass in tests and in the running app on real Yahoo/FRED data. Nothing committed. |
| **Next 3 actions** | 1. Commit the build (you) · 2. Accept or reject Proposed [D007](docs/decisions/D007-pit-handling-yahoo.md), [D008](docs/decisions/D008-price-return-forecasts.md), [D009](docs/decisions/D009-serve-ui-from-api.md) (you) · 3. Set an alert-threshold policy, then start Phase 2 backtesting (you → Claude) |
| **Waiting on** | Your commit; decisions above; project facts (who it is for, time budget); optional SEC EDGAR contact |
| **Say this to Claude to restart** | "Read CLAUDE.md, COMPASS.md and ACTIVITY-LOG.md, start the app (`forwardstate serve`), then start the next backlog task." |

## Log (newest first)

### 2026-11-26 — Phase 1 full build (5 parallel agents + integration)

**Done**
- **Wave 0** (Claude):
  - [contracts/](src/forwardstate/contracts/), [services.py](src/forwardstate/services.py),
    [pit.py](src/forwardstate/pit.py), [testing/](src/forwardstate/testing/),
    [docs/api.md](docs/api.md), [cli.py](src/forwardstate/cli.py) and the schema export.
  - Decisions D004–D007 and Compass v03.
- **Wave 1**, five agents working in separate folders, none running git:
  - data ([ingest/](src/forwardstate/ingest/), [storage/](src/forwardstate/storage/));
  - events, features and forecasting;
  - portfolio, risk and alerts;
  - API ([api/](src/forwardstate/api/));
  - UI ([web/](web/)).
- **Real data:** Yahoo, FRED and FOMC data from 2015-01-02 to 2026-11-25 (EDGAR off).
- **Wave 2:**
  - integration;
  - [acceptance tests](tests/acceptance/test_acceptance.py), AC-01..07;
  - an independent review that found 6 bugs (3 high), all fixed with
    [regression tests](tests/unit/test_review_regressions.py);
  - replay 38 s → 11 s;
  - settings wired into the engines;
  - the API now serves the UI.
- **Browser walkthrough on real data:** research (JPM, GS), portfolio candidates, a March 2023
  replay (the SVB-week alerts fire), and reproduce → Match. Checked at 375 px with no horizontal
  scroll.
- **Wave 3:** [A002](docs/approaches/A002-pit-store-and-adapters.md)–[A005](docs/approaches/A005-react-ui-same-origin.md),
  [D008](docs/decisions/D008-price-return-forecasts.md),
  [D009](docs/decisions/D009-serve-ui-from-api.md),
  the [architecture diagram](docs/diagrams/png/architecture-v1.png) ([PDF](docs/diagrams/pdf/architecture-v1.pdf)),
  [README](README.md), [BACKLOG](docs/BACKLOG.md) and Compass v04.

**Checks:** 184 Python tests pass, ruff is clean, and the UI passes typecheck, 17 tests and the
build.

**Decisions**
- [D004](docs/decisions/D004-react-fastapi-ui.md), [D005](docs/decisions/D005-open-data-sources.md),
  [D006](docs/decisions/D006-cut-list-keeps-five-banks.md): Accepted (your choices).
- [D007](docs/decisions/D007-pit-handling-yahoo.md), [D008](docs/decisions/D008-price-return-forecasts.md),
  [D009](docs/decisions/D009-serve-ui-from-api.md): Proposed.

**Not done**
- No backtest or calibration (Phase 2). Probabilities are labelled simulated and uncalibrated.
- The alert thresholds are still the unapproved examples, and the 5% CVaR rule is noisy.
- EDGAR is disabled. The UI bundle is not code-split. Nothing is committed.
- The desktop app's preview manager would not start the Vite dev server, so the walkthrough used
  `forwardstate serve` on port 8000 ([D009](docs/decisions/D009-serve-ui-from-api.md)).

### 2026-11-25 — Rules review and fixes

**Done**
- Reviewed the working rules and found 8 gaps. Fixed the 4 that were Claude's to fix:
  - [COMPASS.md](COMPASS.md) v01 → v02: "Right now" phase changed from 1 to 0 to match the
    phase map. v01 archived to [docs/compass-history/COMPASS-v01.md](docs/compass-history/COMPASS-v01.md).
  - This log: added the code scaffold work that the entry below left out.
  - [D003 v2](docs/decisions/D003-python-stack.md): evidence now records the real install and
    test run.
  - [A001 — BRD package layout](docs/approaches/A001-brd-package-layout.md): new approach file, status Kept.
- Updated [DECISIONS.md](docs/decisions/DECISIONS.md), [approaches INDEX.md](docs/approaches/INDEX.md)
  and [BACKLOG.md](docs/BACKLOG.md).

**Decisions**
- [D003 v2 — Python stack](docs/decisions/D003-python-stack.md) · still Proposed (evidence only)

**Not done**
- Cut-list clash: [COMPASS.md](COMPASS.md) cut item 2 ("JPM + one peer") conflicts with AC-01
  ("any of the five banks"). This needs your decision.
- Gaps in the git deny list in [.claude/settings.json](.claude/settings.json): `git -c`, `apply`,
  `am`, `worktree`, `submodule`, `update-ref`, `gc`/`prune`, `notes`. This needs your decision.
- Project-fact blanks are still open. Mermaid renderer (`mmdc`) not installed. Nothing committed.

### 2026-11-25 — Code scaffold (added during review; left out of the entry below)

**Done**
- Copied the BRD into [docs/ForwardState_BRD_Technical_Scope.pdf](docs/ForwardState_BRD_Technical_Scope.pdf).
- Created [pyproject.toml](pyproject.toml), the [src/forwardstate/](src/forwardstate/) packages,
  `app/streamlit_app.py` (removed 2026-11-26, see D004),
  [configs/sectors/financials.yaml](configs/sectors/financials.yaml),
  [configs/risk.example.yaml](configs/risk.example.yaml),
  [data/fixtures/README.md](data/fixtures/README.md),
  [tests/unit/test_scaffold.py](tests/unit/test_scaffold.py), [.gitignore](.gitignore) and the
  README content.
- Verified: local `.venv` install OK, 2 tests passed, ruff clean.

**Not done**
- No features. The dashboard is a placeholder. Nothing committed.

### 2026-11-25 — Working rules and docs structure

**Done**
- Wrote the working rules into [CLAUDE.md](CLAUDE.md).
- Created [COMPASS.md](COMPASS.md) v01, this log, [docs/BACKLOG.md](docs/BACKLOG.md).
- Created decision and approach templates and indexes:
  [DECISIONS.md](docs/decisions/DECISIONS.md), [INDEX.md](docs/approaches/INDEX.md).
- Added git deny rules to [.claude/settings.json](.claude/settings.json).
- Added a "Where things live" map to [README.md](README.md).

**Decisions**
- [D001 — working rules](docs/decisions/D001-working-rules.md) · Accepted
- [D002 — decision support only, no trading](docs/decisions/D002-decision-support-only.md) · Accepted (BRD "Agreed")
- [D003 — Python stack](docs/decisions/D003-python-stack.md) · Proposed

**Not done**
- No code changes in this step (the scaffold was built separately; see the entry above). No diagrams. Nothing committed (you commit).
- Project-fact blanks still open.

# Decisions

Never edit a decision in place. See the rules in [CLAUDE.md](../../CLAUDE.md#4-decisions--never-edited-in-place).
New decision: copy [_TEMPLATE.md](_TEMPLATE.md).

## Decision changes (newest first)

| Date | Decision | Before | Now | Trigger / evidence | Compass |
|---|---|---|---|---|---|
| 2026-11-26 | [D009](D009-serve-ui-from-api.md) | UI served by Vite dev server | Proposed: API serves built UI on one port | Preview manager couldn't start Vite; browser walkthrough | v04 |
| 2026-11-26 | [D008](D008-price-return-forecasts.md) | Forecasts used total (dividend-adjusted) returns | Proposed: price returns, splits only | Independent review finding 4; JPM 2y base +21.3% → +17.9% | v04 |
| 2026-11-25 | [D007](D007-pit-handling-yahoo.md) | — | Proposed: raw + corporate actions, inferred availability | D005 picks Yahoo, which has no vintages | v03 |
| 2026-11-25 | [D006](D006-cut-list-keeps-five-banks.md) | Cut item 2 allowed JPM + 1 peer | All five banks kept in data and tests | User choice; AC-01 | v03 |
| 2026-11-25 | [D005](D005-open-data-sources.md) | No data source chosen | Yahoo + FRED + EDGAR + Fed calendar | User choice | v03 |
| 2026-11-25 | [D004](D004-react-fastapi-ui.md) | Streamlit placeholder | React + FastAPI | User choice | v03 |
| 2026-11-25 | [D003 v2](D003-python-stack.md) | Evidence: tests "not re-run" | Evidence: install OK, 2 tests passed, lint clean; still Proposed | Rules review; pytest + ruff run | v02 |
| 2026-11-25 | [D003](D003-python-stack.md) | — | Proposed: Python stack as scaffolded | Scaffold + BRD proposal | v01 |
| 2026-11-25 | [D002](D002-decision-support-only.md) | — | Accepted: no trading | BRD "Agreed" | v01 |
| 2026-11-25 | [D001](D001-working-rules.md) | — | Accepted: working rules | User request | v01 |

## Decisions list

| ID | Decision | Status |
|---|---|---|
| [D001](D001-working-rules.md) | Use the working rules in CLAUDE.md | Accepted |
| [D002](D002-decision-support-only.md) | Decision support only, never trade execution | Accepted |
| [D003](D003-python-stack.md) | Python stack as in pyproject.toml for the MVP | Proposed |
| [D004](D004-react-fastapi-ui.md) | React + TypeScript web app over a FastAPI backend | Accepted |
| [D005](D005-open-data-sources.md) | Yahoo Finance + FRED + SEC EDGAR + Fed calendar | Accepted |
| [D006](D006-cut-list-keeps-five-banks.md) | All five banks stay in data and tests | Accepted |
| [D007](D007-pit-handling-yahoo.md) | Point-in-time rules for restated Yahoo data | Proposed |
| [D008](D008-price-return-forecasts.md) | Forecasts are price returns (dividends excluded) | Proposed |
| [D009](D009-serve-ui-from-api.md) | API serves the built UI from the same address | Proposed |

## Learnings

| Date | Learning | Linked to |
|---|---|---|
| 2026-11-25 | A record can go stale the same day it is written (D003 said tests were not run when they had been). Check evidence against the actual run before writing it. | [D003 v2](D003-python-stack.md) |
| 2026-11-26 | Unit tests passed while 6 real bugs remained (3 high). Each agent tested its own layer against fakes; the bugs lived between layers and over time (cooldown state, window lengths, total vs price return). An independent reviewer given the code, not our conclusions, found them. | [D008](D008-price-return-forecasts.md), [A004](../approaches/A004-portfolio-risk-alerts.md) |
| 2026-11-26 | The example alert thresholds fire almost every week on bank stocks (20-day CVaR is normally ~15%, threshold 5%). Thresholds must come from an approved policy. | [A004](../approaches/A004-portfolio-risk-alerts.md) |

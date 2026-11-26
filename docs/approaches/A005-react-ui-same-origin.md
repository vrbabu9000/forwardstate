# A005 — React UI, served by the API from the same origin

| Field | Value |
|---|---|
| Date | 2026-11-26 |
| Area | UI and workflow |
| Status | Kept |
| Replaces | Streamlit placeholder (removed) |

## What changed

- **Before:** A one-page Streamlit placeholder.
- **Now:** A Vite + React 19 + TypeScript app (`web/`). `npm run build` produces `web/dist`, which
  `forwardstate serve` serves from the same address as `/api`.
- **Why:** You asked for a proper UI ([D004](../decisions/D004-react-fastapi-ui.md)). The app's
  preview manager would not start the Vite dev server, while one server for both the UI and the
  API worked and needs no separate address or proxy
  ([D009](../decisions/D009-serve-ui-from-api.md)).

## The idea (3 lines)

1. TypeScript types are generated from the pydantic contracts:
   `scripts/export_schema.py` → `npm run gen:types`.
2. Mock mode (`npm run dev:mocks`) uses labelled synthetic data, so the UI works offline.
3. Every view shows the data's origin (real, derived or synthetic), its freshness, a "replay
   mode" banner and the decision-boundary text. A test scans the UI for trading words.

## How we tested it

- `cd web && npm run typecheck && npm test && npm run build`: 17 tests.
- A browser walkthrough on real data covering AC-01 and AC-03 to AC-06.
- No horizontal scroll at 375 px (checked with `scrollWidth`).

## Result (numbers first)

| Measure | Before | After | How measured |
|---|---|---|---|
| UI tests | 0 | 17 passed | vitest |
| Page width at 375 px | — | 375 (no horizontal scroll) | `document.documentElement.scrollWidth` |
| Production bundle | — | 1.03 MB JS (306 kB gzipped) | vite build |

## Verdict

Keep. The bundle is large because of the chart libraries; code-splitting is a later polish item.

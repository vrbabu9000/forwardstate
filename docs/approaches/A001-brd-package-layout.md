# A001 — BRD package layout

| Field | Value |
|---|---|
| Date | 2026-11-25 |
| Area | Code structure |
| Status | Kept |
| Replaces | — |

## What changed

- **Before:** The repo held only a one-line README.
- **Now:** It is one installable Python package with a sub-package for each BRD layer, plus
  `app/`, `configs/`, `data/fixtures/`, `tests/` and `docs/`.
- **Why:** This follows the structure the BRD suggests (p.15) and its six layers (p.9), so each
  requirement has an obvious home.

## The idea (3 lines)

1. `src/forwardstate/` has one sub-package per layer: ingest, storage, contracts, events,
   features, forecasting, portfolio, risk and alerts.
2. Industry knowledge lives in `industries/<sector>/` plus `configs/sectors/<sector>.yaml`, so new
   sectors plug in without changing the shared engine (BRD p.11, AC-07).
3. It ships as a single app with separate packages, not microservices (BRD p.9).

## How we tested it

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/pytest
.venv/bin/ruff check .
```

[tests/unit/test_scaffold.py](../../tests/unit/test_scaffold.py) checks that every package imports
and that the financials universe matches the BRD.

## Result (numbers first)

| Measure | Before | After | How measured |
|---|---|---|---|
| Packages that import | 0 | 12 of 12 | pytest |
| Tests passing | 0 | 2 of 2 | pytest, Python 3.10.6 |
| Lint errors | — | 0 | ruff check |

This shows only that the structure works. No features exist yet.

## Verdict

Keep — it maps one-to-one to the BRD layers and installs cleanly. Revisit if a layer turns out to
need splitting.

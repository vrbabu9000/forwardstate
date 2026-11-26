# D003 — Python stack for the MVP

| Field | Value |
|---|---|
| Status | Proposed |
| Date | 2026-11-25 |
| Current version | v2 |

## Decision (one line)

Build the MVP in Python 3.10+ with pandas, NumPy, SciPy, statsmodels, DuckDB/Parquet, pydantic,
Streamlit and pytest (CVXPY optional).

## Why

It is the stack the BRD proposes and the one the scaffold in [pyproject.toml](../../pyproject.toml)
already uses. Changing it now would cost time for no known gain.

## Options considered

| Option | For | Against |
|---|---|---|
| Python stack as in pyproject (chosen) | Already scaffolded; matches BRD | — |
| Swap pandas for Polars | Often faster *(unmeasured here)* | Not needed at MVP size; extra learning |

## Evidence

BRD lists it as "Proposed", not approved. Scaffold installs and runs `pytest` *(not re-run in this session)*.

v2: verified on 2026-11-25 with Python 3.10.6 — `pip install -e ".[dev]"` succeeded, `pytest`
gave 2 passed, `ruff check .` was clean. The `[app]` (Streamlit) and `[optimize]` (CVXPY) extras
were not installed or tested.

## Version history

### v1 · 2026-11-25 · trigger: scaffold already exists; BRD proposal

Keep the stack in pyproject.toml for Phase 1.

### v2 · 2026-11-25 · trigger: rules review found the evidence out of date

Decision unchanged: keep the stack in pyproject.toml for Phase 1. Status stays Proposed.
Evidence now records an actual install and test run (see Evidence, v2). Note: `pydantic` is
not in the BRD's suggested stack; it was added for the versioned data contracts.

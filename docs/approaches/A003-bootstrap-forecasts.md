# A003 — Block-bootstrap scenarios with a transparent drift blend

| Field | Value |
|---|---|
| Date | 2026-11-26 |
| Area | Forecasting |
| Status | Kept (baseline; Phase 2 will test it) |
| Replaces | — |

## What changed

- **Before:** There were no forecasts.
- **Now:** Optimistic, base and pessimistic cases (the 90th, 50th and 10th percentiles) for
  short (20 days), medium (126 days) and long (504 days) horizons. The drift is split into named
  drivers.
- **Why:** The BRD asks for a transparent baseline first (FC-05). The bootstrap keeps the
  correlation between banks, so the portfolio layer can reuse it (PF-03).

## The idea (3 lines)

1. A stationary block bootstrap (mean block of 5 days) resamples whole days of joint price
   returns.
2. Base drift = shrunk history + a weighted analyst-target gap + rate, earnings and market
   assumption effects.
3. Status is unavailable below 250 days of history, low below 750 days or when the horizon is
   longer than a third of the history, and never high, because nothing is calibrated yet.

## How we tested it

- `.venv/bin/pytest tests/unit/test_forecasting_engine.py tests/acceptance` covers AC-02 and
  AC-03, determinism, and a point-in-time truncation test.
- The review regression test `test_finding4` checks that forecasts use price returns, not total
  returns ([D008](../decisions/D008-price-return-forecasts.md)).

## Result (numbers first)

| Measure | Before | After | How measured |
|---|---|---|---|
| 5 banks × 3 horizons, fixture | — | 0.7 s cold | Agent B timing |
| 5 banks × 3 horizons, real data | — | ~3.5 s | `time` in the shell |
| JPM 2-year base case: total → price returns | +21.3% | +17.9% | real data, as of 2026-11-25 |

## Verdict

Keep as the Phase 1 baseline. Phase 2 must measure forecast error and interval coverage against
a no-change baseline before anyone relies on it.

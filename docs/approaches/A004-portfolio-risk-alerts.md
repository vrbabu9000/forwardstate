# A004 — Simulated portfolio risk, SLSQP candidates and replayable alerts

| Field | Value |
|---|---|
| Date | 2026-11-26 |
| Area | Portfolio, risk, alerts |
| Status | Kept |
| Replaces | — |

## What changed

- **Before:** There was no portfolio or alert logic.
- **Now:**
  - Buy-and-hold risk is measured on the correlated simulated paths.
  - Long-only mean-variance candidates are found with scipy SLSQP, using Ledoit-Wolf shrinkage
    for the covariance.
  - 5 alert rule types, with a lifecycle (new, acknowledged, resolved, superseded) and a
    day-by-day replay.
- **Why:** These cover AC-04 and AC-05, and keep the rule that ForwardState never trades
  ([D002](../decisions/D002-decision-support-only.md)).

## The idea (3 lines)

1. **Risk numbers** come from one shared simulation: CVaR 95, the chance of losing more than 5%
   or 10%, median drawdown and concentration.
2. **Candidate mixes** are compared with "no change" and labelled as options, not instructions.
   Constraints that can't be met are rejected with a reason, never silently relaxed.
3. **Alerts** carry evidence, a projected loss, and a hold vs 25% cash vs 50% cash comparison.

## How we tested it

- `tests/unit/test_portfolio_engine.py`, `test_alerts_*.py`, `test_risk_metrics.py` (33 tests).
- `tests/acceptance` covers AC-04 and AC-05.
- `tests/unit/test_review_regressions.py` (findings 1–3).

## Result (numbers first)

| Measure | Before | After | How measured |
|---|---|---|---|
| `event_shock` alerts on real March 2023 data | 0 (could never fire) | fires 14 Mar 2023 on the SVB-day JPM move | browser replay, after review fix |
| Earlier-dated alert blocked by a later one | yes (bug) | no | `test_finding1` |
| Optimize, real data, warm | — | 0.5 s | httpx timing |

## Verdict

Keep. The example alert thresholds are noisy on bank stocks: the 5% CVaR rule fires almost
every week. They need an approved policy (BRD p.15), which is an open decision.

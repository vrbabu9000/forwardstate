# D008 — Forecasts are price returns

| Field | Value |
|---|---|
| Status | Proposed |
| Date | 2026-11-26 |
| Current version | v1 |

## Decision (one line)

Scenario forecasts simulate split-adjusted *price* returns, with dividends left out, and are
applied to the raw start price.

## Why

The forecasts are labelled "price return", they are applied to today's price, and they are
blended with analyst *price* targets. Including dividends overstated the projected prices. The
independent review found this, and the BRD asks to distinguish price return from total return
(p.6).

## Options considered

| Option | For | Against |
|---|---|---|
| Price returns (chosen) | Consistent with price targets and projected prices | Leaves out dividend income |
| Total returns, labelled as such | Includes income | Can't show a projected *price*; mixes with price targets |

## Evidence

JPM over 5 years: total return +114.8% vs price return +89.7%, about 2.4 percentage points a year.
On real data as of 2026-11-25, the JPM 2-year base case went from +21.3% to +17.9%.
Regression test: `tests/unit/test_review_regressions.py::test_finding4_forecast_uses_price_not_total_returns`.

## Version history

### v1 · 2026-11-26 · trigger: independent backend review, finding 4

Forecasts use `forecasting.engine.price_returns` (splits only). Portfolio risk still uses the same
simulation, so the risk numbers are on price return too, with the cash yield added explicitly.

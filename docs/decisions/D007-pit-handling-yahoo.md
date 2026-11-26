# D007 — Point-in-time handling for Yahoo data

| Field | Value |
|---|---|
| Status | Proposed |
| Date | 2026-11-25 |
| Current version | v1 |

## Decision (one line)

Store Yahoo's raw closes and corporate actions with the time we fetched them. Compute adjusted
prices "as of" a date from those actions. Infer `available_at` for each source with stated rules,
and mark every such record `availability_inferred = true`.

## Why

Yahoo silently restates adjusted history and doesn't publish when a value was first available.
Without these rules, a backtest at date T could see data that only appeared later.

Inference rules (v1):

| Record | `available_at` |
|---|---|
| Daily bar | Trading date 16:00 America/New_York, plus 15 minutes |
| Earnings | Earnings timestamp from Yahoo if given; otherwise the 8-K filing time from EDGAR; otherwise date 07:00 ET (before market open), marked low confidence |
| FRED series | The observation date plus that series' usual publication lag (for example, +1 business day for DFF) |
| FOMC decision | Statement date 14:00 ET |
| Analyst action | The action date at 23:59 ET, a conservative choice |
| Derived shock event | The close of the shock day |

## Options considered

| Option | For | Against |
|---|---|---|
| Raw + actions + inferred availability (chosen) | Honest; reproducible | Inference can be wrong; marked as such |
| Use Yahoo adjusted close as given | Simple | Look-ahead through restatements |

## Evidence

None yet. To be checked in Wave 2 by the point-in-time leak review.

## Version history

### v1 · 2026-11-25 · trigger: D005 chose Yahoo, which has no vintages

Rules as above.

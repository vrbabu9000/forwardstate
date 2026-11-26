# D006 — The cut list keeps all five banks

| Field | Value |
|---|---|
| Status | Accepted |
| Date | 2026-11-25 |
| Current version | v1 |

## Decision (one line)

All five banks (JPM, BAC, C, MS, GS) always stay in the data, models and tests. If time runs
short, only the dashboard's peer views may be trimmed.

## Why

The old cut item 2 ("JPM + one peer") would make exit check AC-01 fail. AC-01 needs "any of
the five banks". The five-bank universe is marked "Agreed" in the BRD.

## Options considered

| Option | For | Against |
|---|---|---|
| Keep all five in data (chosen) | AC-01 still passes | No time saved on data |
| Allow cutting to JPM + 1 | Saves time | AC-01 fails |

## Evidence

The user chose it on 2026-11-25. See BRD p.3 and p.12 (AC-01).

## Version history

### v1 · 2026-11-25 · trigger: rules review found a clash between the cut list and AC-01

Cut item 2 now reads: "Dashboard peer views (keep all five banks in data and tests)".

# A002 — Point-in-time store and open-data adapters

| Field | Value |
|---|---|
| Date | 2026-11-26 |
| Area | Data |
| Status | Kept |
| Replaces | — |

## What changed

- **Before:** There was no data, only an empty `ingest/` and `storage/`.
- **Now:** Adapters for Yahoo, FRED, the Fed calendar and EDGAR feed an append-only DuckDB store.
  The store answers every query "as of" a time.
- **Why:** Real data ([D005](../decisions/D005-open-data-sources.md)) without look-ahead
  ([D007](../decisions/D007-pit-handling-yahoo.md)).

## The idea (3 lines)

1. Every record carries `available_at`. Queries return only what was knowable by `as_of`.
2. A re-fetch that changes a value adds a new version, available at the fetch time. Old answers
   never change.
3. Store raw closes plus splits and dividends, and compute adjusted prices as of the query time.

## How we tested it

- `.venv/bin/pytest tests/unit/test_storage_duckdb.py tests/unit/test_ingest_adapters.py`
  (30 tests, no network). These include an equivalence check against the in-memory
  `FixtureStore` at 5 as-of dates.
- Real run: `.venv/bin/forwardstate fetch --start 2015-01-01`.

## Result (numbers first)

| Measure | Before | After | How measured |
|---|---|---|---|
| Daily bars stored | 0 | 2,993 × 7 tickers (2015-01-02 → 2026-11-25) | fetch summary |
| FRED observations | 0 | 18,990 | fetch summary |
| FOMC events | 0 | 191 (97 meetings, real outcomes from the target range) | fetch summary |
| Re-fetch from cache | — | ~5 s, 0 new versions | second run |
| Real 1-month replay, before → after vectorising `pit.adjust_closes` | 38 s | 11 s | `time` on `AlertEngine.replay`, March 2023 |

## Verdict

Keep. The store is point-in-time by construction and reproducible. EDGAR stays off until a
User-Agent is set.

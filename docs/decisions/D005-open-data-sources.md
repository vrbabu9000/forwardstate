# D005 — Real open data, Yahoo Finance for prices

| Field | Value |
|---|---|
| Status | Accepted |
| Date | 2026-11-25 |
| Current version | v1 |

## Decision (one line)

Use free, open data sources: Yahoo Finance (via `yfinance`) for prices, corporate actions,
earnings dates and analyst actions; FRED for rates; SEC EDGAR for filing dates; the Federal
Reserve calendar for FOMC dates.

## Why

The user wants real data, not synthetic. All of these sources are free and need no paid licence.

## Options considered

| Option | For | Against |
|---|---|---|
| Yahoo + open sources (chosen) | Real history; free | Unofficial API that can break; restated history; personal-use terms |
| Fully synthetic | Reproducible; no network | Not real |
| Paid vendor | Point-in-time quality | Cost; not approved |

## Evidence

The user chose it on 2026-11-25.

Limits that apply:
- Yahoo data is for personal, non-commercial use.
- Data is cached locally under `data/cache/` (gitignored) and never redistributed.
- Synthetic data is used only in tests, and is labelled as synthetic.
- Unexpected events are derived from abnormal price moves and labelled "derived". They are not
  news.

## Version history

### v1 · 2026-11-25 · trigger: user choice for the full build

Yahoo Finance, FRED, SEC EDGAR and the Fed calendar. A live Bloomberg-style feed stays out of
scope until Phase 3.

# D002 — Decision support only, no trading

| Field | Value |
|---|---|
| Status | Accepted |
| Date | 2026-11-25 |
| Current version | v1 |

## Decision (one line)

ForwardState raises alerts and shows scenarios; it never executes trades, routes orders or
connects to brokers.

## Why

The human makes every investment decision. Scenarios are not guaranteed price targets.

## Options considered

| Option | For | Against |
|---|---|---|
| Decision support only (chosen) | Matches BRD; lower risk | — |
| Add order execution | — | Out of scope in BRD; high risk |

## Evidence

BRD v1.0 draft ([docs/ForwardState_BRD_Technical_Scope.pdf](../ForwardState_BRD_Technical_Scope.pdf)),
marked "Agreed".

## Version history

### v1 · 2026-11-25 · trigger: BRD v1.0 draft

No trade execution, no broker integration, no order endpoints.

# D004 — React + FastAPI for the UI

| Field | Value |
|---|---|
| Status | Accepted |
| Date | 2026-11-25 |
| Current version | v1 |

## Decision (one line)

The UI is a React + TypeScript web app (`web/`) that calls a FastAPI backend
(`src/forwardstate/api/`) over the Python engine. Streamlit is dropped.

## Why

The user asked for a proper UI. A real web app supports richer charts, layout and interaction
than Streamlit. The frontend and backend can also be built in parallel against a shared API
contract.

## Options considered

| Option | For | Against |
|---|---|---|
| React + FastAPI (chosen) | Polished UI; clean split between frontend and backend; parallel work | More code; two toolchains (Python + Node) |
| Streamlit (BRD proposal) | Fastest; Python only | Limited layout and interactivity |

## Evidence

The user chose it on 2026-11-25. The BRD lists Streamlit only as "Proposed".

## Version history

### v1 · 2026-11-25 · trigger: user choice for the full build

React + TypeScript (Vite) frontend; FastAPI backend; remove the Streamlit placeholder.

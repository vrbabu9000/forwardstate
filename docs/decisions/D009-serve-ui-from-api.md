# D009 — The API serves the built UI from the same address

| Field | Value |
|---|---|
| Status | Proposed |
| Date | 2026-11-26 |
| Current version | v1 |

## Decision (one line)

`forwardstate serve` serves the built React app (`web/dist`) at `/` and the API at `/api`, on one
port (8000). The Vite dev server remains for UI work.

## Why

There is one process to start, with no separate address or proxy for the UI. It also matches how
the app would be deployed. During the build, the desktop app's preview manager would not start
the Vite dev server, while the API server worked.

## Options considered

| Option | For | Against |
|---|---|---|
| Same address: API serves `web/dist` (chosen) | One command, one port; production-like | Needs `npm run build` after UI changes |
| Two servers (Vite proxy → API) | Hot reload while editing the UI | Two processes; failed to start here |

## Evidence

A browser walkthrough on `http://127.0.0.1:8000` covered AC-01, AC-03, AC-04, AC-05 and AC-06 on
real data. The route-spec test excludes only the static fallback route `GET /{path}`.

## Version history

### v1 · 2026-11-26 · trigger: Wave 2 browser walkthrough

`api.app.mount_web_ui` mounts `web/dist` if it exists. API routes are registered first and
always win.

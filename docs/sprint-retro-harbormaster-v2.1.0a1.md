# Sprint Retro — Harbormaster v2.1.0a1

**Date:** 2026-05-09
**Theme:** UI sprint kickoff. Three signals the backend was already
computing — Mermaid graph markup, FleetQ Bridge config state, and
plugin discovery — finally surface in the dashboard. Project-cards
page becomes a status console.

## What landed

| SHA | Subject |
|-----|---------|
| (squash) | feat(ui): mermaid graph + bridge/plugin status panels (#23) |

## Capabilities

### 1 · Project graph render

Mermaid 10.9.1 ESM via CDN, called via `mermaid.run({ nodes })` from
Alpine after each `/api/graph` fetch. Two checkboxes flip
`include_dev_deps` and `transitive` (the v2.0.0a1 lockfile mode).
The dashboard shows projects discovered, edge count, and lockfile
coverage at a glance.

### 2 · `GET /api/bridge/status`

Config-derived FleetQ state: `enabled`, `register_as_bridge`,
`base_url`, `api_token_env`, `api_token_present` (env var non-empty),
writeback gates, `kg_extractor` mode, heartbeat interval. Stays in
the UI process; doesn't try to reach into harbormaster-mcp's
runtime. Color-coded chip in the dashboard: `disabled` /
`token missing` / `configured`.

### 3 · `GET /api/plugins`

JSON wrapper around the v2.0.1 `plugins list` CLI categorization.
Five statuses surface in the dashboard: `loaded`, `not-allowlisted`,
`disabled`, `no-dist-name`, `missing` (allowlist entry without a
matching entry point). Color-coded chips per status.

### 4 · `/api/graph` gains `transitive` query param

Mirrors the v2.0.0a1 MCP tool surface. Default `false` keeps
v2.0.x callers' responses byte-equivalent. New
`projects_with_lockfile` counter in the result envelope.

## Real numbers

- 1 PR opened / merged (#23)
- 10 new unit tests in `test_ui.py`
- Test suite: 520 → **530 pass, 1 skip**
- mypy --strict: 46 source files clean
- ruff: clean
- Backwards-incompatible changes: 0
- Lines changed: +613 / -4

## What worked

- **CDN-only deps stay honored.** Mermaid 10.9.1 added as one
  `<script type="module">` import in `base.html`; pinned URL keeps
  it reproducible. Zero npm, zero bundler.
- **Reuse the plugins_cli categorizer.** `/api/plugins` literally
  imports `_entry_point_distribution_name` and `discover_entry_points`
  from `plugins.py`, mirrors the same five statuses. CLI and HTTP
  views can never drift.
- **Default-off transitive keeps `/api/graph` byte-stable.** External
  tooling that hit v2.0.x's `/api/graph` keeps getting the same
  payload; the new field only appears when explicitly asked.

## What to change / next

- **No live FleetQ bridge state in `/api/bridge/status`.** Surfaces
  config + token presence only. Live session_id / last heartbeat
  needs cross-process plumbing (UI lives in its own process when
  used standalone). Defer to a future phase if anyone asks.
- **No mobile-optimized graph view.** Mermaid's responsive output is
  OK but a wide dependency graph still needs horizontal scroll on
  phones. Consider a "compact mode" toggle in v2.1.0a4+ if the
  phone-control story takes off.
- **Color semantics use ad-hoc Tailwind classes.** A small Tailwind
  preset for status chips (`emerald` / `amber` / `rose` / `gray`)
  would be cleaner. Premature for two endpoints' worth of usage.

## Action items for the next sprint (v2.1.0a2)

1. **Project detail page at `/projects/{name}`.** Server-side render
   from `project_status` with git log + Serena memories + path. Card
   click navigates to detail. Sets up the surface the v2.1.0a4
   "Ask this project" form will live on.

## Out-of-scope (still)

- Tauri / Electron desktop UI wrapper
- agent.request → MCP dispatcher wiring
- Live (runtime) FleetQ bridge state in /api/bridge/status
- Headless browser tests (we trust Tailwind / Alpine / Mermaid behaviour)

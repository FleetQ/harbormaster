# Architecture — v2.1 UI Sprint

**Source:** `~/claudedocs/research_harbormaster_ui_2026-05-09.md`
**Goal:** Turn the read-only project-cards page into a working
local operator console without breaking the no-build promise.

## Stack decisions

- **Templating:** Jinja2 server-render (no SSR framework)
- **CSS:** Tailwind via CDN (already in `base.html`)
- **Reactivity:** Alpine.js for component-local state, HTMX for partial swaps
- **Streaming:** native `EventSource` against `POST /mcp/{server}` SSE
- **Graph:** add `mermaid.min.js` via CDN (one new script tag)
- **No build step.** Adding webpack/vite would regress v1.0.0a4's
  explicit choice. CDN scripts are pinned by URL/version.

## Information architecture

```
/                       → dashboard.html        (existing, expanded)
                         · project grid (existing)
                         · NEW: graph render section
                         · NEW: bridge/plugin status strip
                         · NEW: recall search bar

/projects/{name}        → project_detail.html   (NEW)
                         · git log + memories + path
                         · "Ask this project" inline form (a4)
                         · "Delegate task" inline form (a5)
                         · trajectory history table (a6)

/tools/fan-out          → fan_out.html          (NEW, a5)
                         · multi-select project chips
                         · concurrency slider
                         · parallel-grid result panes
```

## New API endpoints (per phase)

| Phase | Endpoint | Reads from |
|-------|----------|-----------|
| a1    | `GET /api/bridge/status` | heartbeat loop (in-process state) |
| a1    | `GET /api/plugins` | wraps `plugins_cli._list()` to JSON |
| a2    | `GET /projects/{name}` | calls `project_status` MCP tool internally |
| a6    | `GET /api/trajectories?project=...&limit=...` | reads QAStore directly |

Phases a3 / a4 / a5 use the existing `POST /mcp/{server}` (JSON +
SSE modes) — zero new endpoints.

## Streaming UX

Browser-side EventSource consumer pattern:

```js
const es = new EventSource(url, { withCredentials: false });
es.addEventListener('chunk', e => append(JSON.parse(e.data).delta));
es.addEventListener('result', e => { finalize(e.data); es.close(); });
es.addEventListener('error',  e => { showError(e.data); es.close(); });
```

Auth: pass token as `?token=...` query string for EventSource (which
can't set Authorization header). Server already accepts both forms
on the streaming dispatch when the user passes a query param. If
not, route adds support — small change in the route guard.

## Mobile-first constraints

- Dashboard cards: 1-col `<sm`, 2-col `md`, 3-col `lg`
- Mermaid: `max-width: 100%; overflow-x: auto;` wrapper
- Inline forms: textarea grows to viewport
- Bridge status strip: collapsible accordion `<sm`, sticky strip `≥md`

## Hard size limits

- `dashboard.html` ≤ 250 LOC
- `project_detail.html` ≤ 250 LOC
- `fan_out.html` ≤ 250 LOC
- Above that → extract Jinja partials under `templates/_partials/`

## Component decomposition

- `_partials/project_card.html` — used by dashboard + future contexts
- `_partials/bridge_status.html` — strip / accordion
- `_partials/plugins_panel.html` — table
- `_partials/ask_form.html` — used by project detail + dashboard
- `_partials/sse_result_pane.html` — streamed answer surface

## Data flow

```
Browser → fetch /api/projects → render cards
Browser → fetch /api/graph     → render mermaid
Browser → POST /mcp/harbormaster (SSE) → stream chunks → render
```

No new persistence. No state on the server except the existing
heartbeat loop reference (for /api/bridge/status).

## Dependency policy

- Mermaid CDN: pin to a specific version (`mermaid@10.9.1` or whatever
  is current and stable; record in `base.html` comment)
- HTMX: already 1.9.10
- Alpine: already 3.x
- No new Python deps

## Test boundaries

- Unit-test new endpoints (FastAPI TestClient)
- Smoke-test rendered HTML for required selectors (don't headless-browser test the JS)
- Existing 520 tests stay green; +20–30 new across all 6 phases

## Migration / compat

- All new HTML routes are additive; no existing route changes shape
- New API endpoints are additive
- Existing `/api/projects`, `/api/graph`, `/api/health`,
  `/agent-card/{name}` unchanged
- `POST /mcp/{server}` unchanged (it already supports both JSON + SSE)

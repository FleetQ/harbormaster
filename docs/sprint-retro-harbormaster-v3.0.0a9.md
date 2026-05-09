# Sprint Retro — Harbormaster v3.0.0a9

**Date:** 2026-05-09
**Theme:** Two related UX fixes for operators outside of laptop-on-desk:
mobile graph viewport + URL state for the fan-out form.

## What landed

### `harbormaster` (this repo)

| SHA | Subject |
|-----|---------|
| `d27787c` | feat(ui): mobile-friendly graph + URL state encoding (v3.0.0a9) |

## Capabilities (this sprint)

### 1 · Touch-friendly graph viewport

Before: `<pre class="mermaid">` rendered the SVG inline with
`overflow-x-auto`. On phones the panel either overflowed the
viewport horizontally (with ugly outer scroll) or got cropped.
There was no way to vertically pan a tall graph either.

After: the wrapping `<div>` got `overflow-x-auto overflow-y-auto
max-h-[60vh] touch-pan-x touch-pan-y`. The browser's native pan
handles touch gestures; the 60vh cap keeps the panel from blowing
out small screens. Once Mermaid replaces the `<pre>` with the SVG,
the same container scrolls.

### 2 · URL state for fan-out form

Before: the fan-out form had no persistence. Reload the page,
filters reset; share the URL with a colleague, they got the empty
default form.

After: form state encodes as URL search params. `restoreFromUrl()`
reads on mount; `persistToUrl()` writes on submit + selectAll/None.

```
/tools/fan-out?q=auth%20flow&targets=app-a,app-b&concurrency=8&turns=5
```

Encoded params (all optional, omitted when at defaults):

| param         | meaning                                  |
|---------------|------------------------------------------|
| `q`           | question text                            |
| `host`        | host filter (omitted when "local")       |
| `concurrency` | max_concurrency (omitted when 5)         |
| `turns`       | max_turns (omitted when 3)               |
| `targets`     | comma-joined project names               |

Uses `window.history.replaceState` rather than `pushState` so back
button doesn't get polluted with one entry per keystroke.

### 3 · Sharable links

Two operators on the same Harbormaster install can now share fan-out
queries by URL:

> "Hey, run this:
> `https://harbormaster.local/tools/fan-out?q=migration%20status&targets=billing,reports`"

## Real numbers

- 1/1 v3.0.0a8-retro action item shipped
- 0 PRs opened — merged `feat/v3.0-mobile-graph-urlstate` directly via `--no-ff`
- 3 new unit tests
- Test suite delta: 618 + 1 skip → **621 + 1 skip**
- `mypy --strict` clean across 48 source files
- `ruff` clean across `src/` and `tests/`
- 0 backwards-incompatible changes — additive viewport classes +
  URL params with default-omit serialization

## What worked

- **`replaceState` not `pushState`.** Operators who kept tweaking the
  question would have ended up with N history entries per session.
  Replace keeps the URL in sync without polluting back-button.
- **Default-omit URL serialization.** `concurrency=5` is the default;
  the URL shouldn't include it. Only deviations get serialized,
  keeping URLs short and the difference between "default" and
  "explicitly customised" visible at a glance.
- **`touch-pan-x touch-pan-y` over a JS gesture library.** Modern
  mobile browsers natively handle pan when the touch-action CSS
  property is set. No 200-line gesture-handler script needed.

## What to change / next

- **No graph zoom.** Pan works; pinch-zoom on Mermaid SVG is harder
  (Mermaid renders fixed-size SVG, would need a transform wrapper +
  pinch listener). Defer — pan + 60vh covers most cases.
- **URL state only on fan-out.** The same pattern would help
  `/api/recall` (recall search filters) and the dashboard project
  filter. Defer — fan-out has the highest "share this" value.

## Action items for the next sprint (v3.0.0a10)

1. **Headless browser tests (Playwright).** UI shipped in v2.1 with
   smoke jobs that only check HTTP status. v3.0.0a10 adds real
   browser-driven tests for dashboard, project_detail, fan-out, and
   ask form flows. Tests gated by `pytest -m browser`; new CI job
   `smoke-ui-browser` (Ubuntu only, Playwright Linux runners). Cover:
   dashboard renders, project_detail navigates, ask form streams,
   fan-out submits, trajectory refreshes after ask.

## Out-of-scope (still)

- Tauri / Electron desktop UI — no demand.
- Relay-binary path (Path B) — Path C HTTP tunnel covers it.
- IDE extension — MCP works with any MCP client.
- pnpm v5 lockfile support — pre-2022 format.
- Multi-worker dispatch pool — defer until thread-safety proven.
- Session-cookie auth + CSRF — defer until multi-operator UI is real.
- Per-card host selector — fan-out covers cross-host.
- Mermaid pinch-zoom — pan + 60vh sufficient for now.
- URL state on recall / dashboard — fan-out has highest share value.

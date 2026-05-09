# Sprint Retro — Harbormaster v3.0.0a8

**Date:** 2026-05-09
**Theme:** Glued the project_detail UI together. Asking or delegating
no longer leaves the trajectory section stale.

## What landed

### `harbormaster` (this repo)

| SHA | Subject |
|-----|---------|
| `7cedf83` | feat(ui): cross-section trajectory refresh events (v3.0.0a8) |

## Capabilities (this sprint)

### 1 · `hm:trajectory:dirty` custom event

Wire shape: a CustomEvent dispatched on `window` with detail
`{ project, host }`. Fired by:
- `_partials/_ask_form_script.html` (askForm) on stream completion
- `_partials/delegate_form.html` on delegate stream completion

Listener: `project_detail.html`'s trajectory section, via
`x-on:hm:trajectory:dirty.window`. Reloads when the event's project
matches the section's scope.

```html
<section x-data="trajectoryList({ project: ..., host: ... })"
         x-init="load()"
         x-on:hm:trajectory:dirty.window="if ($event.detail && $event.detail.project === project) load()">
```

```javascript
// At end of askForm/delegateForm successful stream:
window.dispatchEvent(new CustomEvent('hm:trajectory:dirty', {
  detail: { project: this.project, host: this.host || 'local' },
}));
```

### 2 · Forward-compatible event surface

The dashboard's per-card inline ask form (v3.0.0a7) shares the same
`askForm()` script, so it dispatches the event too — but the
dashboard has no trajectory listener today. When a future trajectory
panel lands on the dashboard, no extra wiring needed; the dispatch
is already primed.

## Real numbers

- 1/1 v3.0.0a7-retro action item shipped
- 0 PRs opened — merged `feat/v3.0-cross-section-events` directly via `--no-ff`
- 3 new unit tests (dispatch present, listener with guard, shared
  dispatch on dashboard)
- Test suite delta: 615 + 1 skip → **618 + 1 skip**
- `mypy --strict` clean across 48 source files
- `ruff` clean across `src/` and `tests/`
- 0 backwards-incompatible changes — additive event surface

## What worked

- **Project-match guard in the listener.** The `if ($event.detail.project === project)` guard
  means a fan-out form firing many events (one per project) doesn't
  cause the trajectory section to load N times. Each section reloads
  exactly when a relevant event arrives.
- **`window.dispatchEvent` over Alpine `$dispatch`.** `$dispatch`
  bubbles up the Alpine component tree, but our trajectory section
  is a sibling of the form, not an ancestor. `window.dispatchEvent`
  + `.window` modifier on the listener is the simpler cross-scope
  idiom. Same pattern reusable anywhere on the page.
- **Empty detail check (`$event.detail &&`).** Guards against future
  callers dispatching the event with no detail at all (e.g.
  HTMX-triggered global refresh button) — listener degrades to no-op
  rather than throwing.

## What to change / next

- **Trajectory load is unthrottled.** Two rapid asks in 50ms would
  trigger two loads. Acceptable today — `/api/trajectories` is a
  cheap sqlite read. Flag for v4 if it ever shows up in profiles.
- **No optimistic insert.** The trajectory section waits for the
  next `/api/trajectories` round-trip rather than appending the
  just-streamed result client-side. Round-trip is fast; complexity
  trade-off favours server-as-source-of-truth.

## Action items for the next sprint (v3.0.0a9)

1. **Mobile-optimised graph + URL state encoding.** Mermaid graph
   on mobile is non-interactive (no zoom/pan on touch). Fan-out
   form filters reset on page reload (no URL state). Wire pinch-zoom
   + drag-pan via Mermaid's init config; encode fan-out form state
   into URL search params for sharable links.

## Out-of-scope (still)

- Tauri / Electron desktop UI — no demand.
- Relay-binary path (Path B) — Path C HTTP tunnel covers it.
- IDE extension — MCP works with any MCP client.
- pnpm v5 lockfile support — pre-2022 format.
- Multi-worker dispatch pool — defer until thread-safety proven.
- Session-cookie auth + CSRF — defer until multi-operator UI is real.
- Per-card host selector — fan-out covers cross-host.
- Optimistic trajectory insert — server-as-truth simpler.

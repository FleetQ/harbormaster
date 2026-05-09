# Sprint Retro — Harbormaster v6.0.0a4

**Date:** 2026-05-09
**Theme:** Made the v5.0.0a5 graph zoom shortcuts discoverable. `?`
toggles a popover listing every keyboard shortcut on the dashboard.

## What landed

| SHA | Subject |
|-----|---------|
| `1656754` | feat(ui): keyboard shortcut help popover |

## Capabilities

### 1 · `?` toggles a fixed-position popover

Same form-field guard as v5.0.0a5 — typing into an INPUT / TEXTAREA /
SELECT never triggers the popover. Outside form fields, `?` toggles
open / closed.

`Escape` dismisses (and outside-click). The fixed pill at
`bottom-4 right-4` is the pointer-friendly entry point.

### 2 · Single source of truth for shortcuts

```js
shortcuts: [
  { scope: 'graph zoom (dashboard)', rows: [
    { keys: '+ / =',     action: 'zoom in' },
    { keys: '- / _',     action: 'zoom out' },
    { keys: '↑ ↓ ← →',   action: 'pan' },
    { keys: 'Esc',       action: 'reset zoom' },
    { keys: 'double-tap', action: 'reset zoom (touch)' },
  ]},
  { scope: 'this popover', rows: [
    { keys: '?',   action: 'toggle keyboard help' },
    { keys: 'Esc', action: 'dismiss popover' },
  ]},
]
```

Future shortcuts (v6.0.0a5+ or v7) get added to this array; the
template renders them automatically with the same `<kbd>` styling.

### 3 · Visual treatment

- Pill (`?`) → button (`×`) when open: same element, just text swap
- `<kbd>` elements styled with monospace + cyan accent
- Footer hint: "Press Esc or ? to dismiss" — surfaces both paths

## Real numbers

- 1/1 v6.0.0a3-retro action item shipped
- 0 PRs opened — merged via `git merge --no-ff`
- 6 new tests (factory, listener, form-field guard, content, pointer
  affordance, click-away)
- Test suite delta: 724 + 2 skips → **730 + 2 skips**
- `mypy --strict` clean across 49 source files
- `ruff` clean
- 0 backwards-incompatible changes — pure additive UI

## What worked

- **Same guard idiom as graphZoom.** Both Alpine scopes check
  `INPUT / TEXTAREA / SELECT` to avoid hijacking typing. Tests
  enforce the duplication count (>= 2) so a future copy-paste won't
  silently lose one of them.
- **Single shortcuts array, not template-side hardcoding.** Adding a
  shortcut to v6.0.0a5+ is one push to the array; popover updates
  automatically.
- **Pill + popover share `open` state.** No separate "click button"
  vs. "press ?" handlers; both flip the same boolean. Click-away
  closes via `@click.away`. Three entry points, one source of truth.

## What to change / next

- **Shortcut map duplicates the actual handlers.** If a future PR
  adds a new shortcut to graphZoom but forgets to update the
  shortcuts array, the popover lies. A future helper could derive
  the array from the handlers themselves (decorator pattern in JS).
  Defer.
- **No "show only relevant shortcuts" filtering.** A user on
  project_detail (no graph zoom) still sees graph zoom shortcuts in
  the popover — but project_detail doesn't render the popover today
  anyway. When the popover moves to base.html (v7?), filtering by
  active page kicks in.

## Action items for the next sprint (v6.0.0a5)

1. **Streaming-chunks dispatcher stress.** v4.0.0a6 + v5.0.0a2
   stress proved the dispatcher safe for non-streaming responses.
   v6.0.0a5 covers the streaming SSE path: 50 concurrent chunk-yielding
   handlers via 16-worker pool; verify per-request chunk ordering
   isn't interleaved across requests.

## Out-of-scope (still)

- Tauri / Electron desktop UI — no demand.
- Relay-binary path (Path B) — Path C HTTP tunnel covers it.
- IDE extension — MCP works with any MCP client.
- Session-cookie auth + CSRF — defer until multi-operator UI is real.
- pnpm v5 lockfile support — pre-2022 format.
- Cancel-running-reembed button — defer until observed.
- Reembed run history — defer until needed.
- Per-host stale thresholds — defer until observed.
- Language badge on cards — defer.
- Auto-derived shortcuts array — defer.
- Page-aware popover filtering — defer until popover is global.

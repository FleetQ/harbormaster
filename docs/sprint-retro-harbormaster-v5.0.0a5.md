# Sprint Retro — Harbormaster v5.0.0a5

**Date:** 2026-05-09
**Theme:** Two missing input modalities for the graph viewport — mobile
double-tap-to-reset and desktop keyboard shortcuts. Power users no
longer need to reach for the reset button.

## What landed

| SHA | Subject |
|-----|---------|
| `e558b76` | feat(ui): graph zoom UX polish |

## Capabilities (this sprint)

### 1 · Double-tap-to-reset (touch)

`onTouchStart` tracks the previous tap timestamp. A second tap
within 300ms calls `reset()` instead of starting a pan. The
threshold matches iOS standard "double-tap" detection.

```js
const now = Date.now();
if (now - this._lastTapTime < 300) {
  this.reset();
  this._lastTapTime = 0;
  return;
}
this._lastTapTime = now;
```

### 2 · Keyboard shortcuts (desktop)

`@keydown.window="onKeyDown($event)"` listens globally; the handler
checks `e.target.tagName` first so typing into `INPUT` / `TEXTAREA` /
`SELECT` doesn't pan the graph by accident.

| Key       | Action          |
|-----------|-----------------|
| `+` / `=` | Zoom in 0.1×   |
| `-` / `_` | Zoom out 0.1×  |
| Arrow ←   | Pan right (30px) |
| Arrow →   | Pan left  (30px) |
| Arrow ↑   | Pan down  (30px) |
| Arrow ↓   | Pan up    (30px) |
| Escape    | Reset          |

`preventDefault()` on every handled key so they don't scroll the page.

### 3 · Reset button hint

Title updated: `reset zoom (current: 1.00×) — press Esc or double-tap`.
The shortcuts are discoverable without RTFM.

## Real numbers

- 1/1 v5.0.0a4-retro action item shipped
- 0 PRs opened — merged via `git merge --no-ff`
- 4 new unit tests (double-tap, keyboard cases, form-field guard,
  title hint)
- Test suite delta: 692 + 2 skips → **696 + 2 skips**
- `mypy --strict` clean across 49 source files
- `ruff` clean across `src/` and `tests/`
- 0 backwards-incompatible changes — pure UI additions

## What worked

- **Form-field tag guard.** Without it, typing `+` into the recall
  search box would zoom the graph. The `tag === 'INPUT' ||
  tag === 'TEXTAREA' || tag === 'SELECT'` check is one line and
  prevents the most surprising failure mode.
- **300ms double-tap threshold.** Standard iOS gesture timing — feels
  natural, doesn't accidentally fire on a deliberate slow second tap.
  Matches what every native iOS app does.
- **Reset = Escape.** The `Esc` key for "undo this thing" is a
  cross-platform convention; users find it without docs.
- **`@keydown.window`, not `@keydown` on the panel.** A focused
  graph would otherwise need explicit click-to-focus before
  shortcuts work. Window-level capture + tag-guard is more
  forgiving.

## What to change / next

- **No tooltip showing the keyboard map.** Power users have to
  read the source or the retro to know about the arrow keys.
  A small "?" icon with a popover would surface it. Defer.
- **No customizable shortcuts.** Hardcoded. Operators with non-QWERTY
  layouts (e.g. Dvorak `+` is in a different spot) might find this
  awkward. Defer.

## Action items for the next sprint (v5.0.0a6)

1. **Dashboard project filter + URL state.** Add a text-based filter
   input above the project grid that filters cards by name / path /
   brief substring. Persist filter to URL via `?filter=...` using
   the v3.0.0a9 pattern. Auto-apply on mount.

## Out-of-scope (still)

- Tauri / Electron desktop UI — no demand.
- Relay-binary path (Path B) — Path C HTTP tunnel covers it.
- IDE extension — MCP works with any MCP client.
- Session-cookie auth + CSRF — defer until multi-operator UI is real.
- pnpm v5 lockfile support — pre-2022 format.
- Manual "trigger reembed now" button — defer until needed.
- Reembed ETA estimation — defer until rate signal stabilises.
- Streaming-chunks stress — defer until streaming path bottlenecks.
- Config-driven safety allowlist — keep code-controlled by design.
- Stuck-writeback escalation tier — defer until observed.
- Configurable stale threshold — defer until needed.
- Keyboard shortcut help popover — defer.
- User-customizable shortcuts — defer.

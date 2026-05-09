# Sprint Retro — Harbormaster v4.0.0a3

**Date:** 2026-05-09
**Theme:** Replaced the v3.0.0a9 native-scroll graph viewport with
explicit pinch-zoom + drag-pan handlers. Operators can finally
navigate complex graphs on mobile.

## What landed

| SHA | Subject |
|-----|---------|
| `9412497` | feat(ui): graph pinch-zoom + drag-pan (v4.0.0a3) |

## Capabilities (this sprint)

### 1 · `graphZoom()` Alpine component

State: `scale`, `tx`, `ty`, `dragging`, plus pinch internals.
Transform applied to the wrapper around the Mermaid `<pre>` via
`transform: translate(${tx}px, ${ty}px) scale(${scale})`.

- **Wheel zoom (desktop)** — `e.deltaY` → scale change, anchored on
  cursor position so zoom feels natural ("zooming on what you're
  pointing at").
- **Two-finger pinch (mobile)** — `Math.hypot(dx, dy)` of touchpoint
  delta drives scale; `_pinchInitialScale * (dist / _pinchInitialDist)`
  preserves anchor.
- **Single-finger drag-pan** — same path as mouse drag for touch
  devices.
- **Mouse drag-pan** — mousedown captures start, mousemove applies
  delta, mouseup/mouseleave releases.
- **Reset button** — top-right corner; returns to scale=1, tx=0,
  ty=0 with a 0.2s ease for visible feedback.

### 2 · Scale clamps

`_clampScale(s) → max(0.25, min(4, s))`. Prevents:
- Invisible graph at very small scale (0.05× is unusable)
- Runaway scale on rapid wheel-zoom (e.g. trackpad inertia spikes)

### 3 · Cursor + transition feedback

- `cursor: grab` when idle, `grabbing` when dragging
- `transition: transform 0.2s ease` only during reset; disabled
  during user input so pan/zoom feels direct

## Real numbers

- 1/1 v4.0.0a2-retro action item shipped
- 0 PRs opened — merged via `git merge --no-ff`
- 5 new unit tests + 1 v3.0.0a9 test rewritten for the new design
- Test suite delta: 640 + 2 skips → **645 + 2 skips**
- `mypy --strict` clean across 48 source files
- `ruff` clean across `src/` and `tests/`
- 0 backwards-incompatible changes — pure UI replacement

## What worked

- **Cursor-anchored wheel zoom.** The naive implementation zooms
  toward (0,0). Anchoring on `e.clientX/Y` relative to the viewport
  rect makes desktop wheel feel like Figma / Lucid — zoom centres
  where the cursor is.
- **State machine for two→one finger transitions.** When pinching
  ends because one finger lifts, the remaining finger should
  immediately drive a pan, not wait for the user to lift+touch
  again. `onTouchEnd` re-arms `dragging` from the still-down touch
  if pinch was active.
- **Pure JS, no library.** Hammer.js / interact.js would have
  added ~30KB of payload for a feature that needs ~80 lines.

## What to change / next

- **No double-tap-to-reset.** Operators have to hit the reset button.
  Worth adding if the reset button proves too small on mobile.
- **No keyboard shortcuts.** Power users on desktop might want
  arrow keys for pan + +/- for zoom. Defer.
- **Scale-anchored on cursor for wheel only.** Pinch is anchored on
  pinch midpoint implicitly via the dist/initialDist ratio, but
  not on the actual centroid of the two touches. On very large
  graphs the apparent zoom drift might be noticeable. Defer until
  someone complains.

## Action items for the next sprint (v4.0.0a4)

1. **Optimistic trajectory insert.** v3.0.0a8 fires
   `hm:trajectory:dirty` and the trajectory section reloads via
   `/api/trajectories`. Round-trip is fast but visible. v4.0.0a4
   prepends a synthetic Q&A entry client-side from the streamed
   answer so the operator sees their result appear instantly,
   then reconciles on next reload.

## Out-of-scope (still)

- Tauri / Electron desktop UI — no demand.
- Relay-binary path (Path B) — Path C HTTP tunnel covers it.
- IDE extension — MCP works with any MCP client.
- pnpm v5 lockfile support — pre-2022 format.
- Multi-worker dispatch pool — gated on profile evidence in v4.0.0a6.
- Session-cookie auth + CSRF — defer until multi-operator UI is real.
- SSE end-to-end browser test — needs backend mocking; defer to a6.
- IE11 / pre-2018 clipboard fallback — modern-browser-only is fine.
- Double-tap-to-reset / keyboard shortcuts on graph zoom — defer.

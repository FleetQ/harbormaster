# Sprint Retro — Harbormaster v5.0.0a4

**Date:** 2026-05-09
**Theme:** Two final polish items on the v4.0.0a4 optimistic trajectory
flow — smooth cross-fade on reconciliation + writeback spinner for slow
flows.

## What landed

| SHA | Subject |
|-----|---------|
| `ba13c88` | feat(ui): optimistic trajectory polish |

## Capabilities (this sprint)

### 1 · 200ms cross-fade on optimistic→real

The v4.0.0a4 optimistic entry rendered with a cyan border and
"● new" badge. When reconciliation happened, the optimistic entry
was REMOVED from the array and the server entry took its slot —
abrupt visual replacement.

Now: `:key` is the content tuple `(project, tool, question)` instead
of `t.id`. The `<li>` DOM node persists across reconciliation; the
new `transition-colors duration-200` Tailwind class animates the
border + bg colour change when `_optimistic` flips to `false`.

`load()`'s reconciliation does in-place merge:

```js
const reconciled = fresh.map((s) => {
  const match = optimistics.find(o =>
    o.project === s.project && o.tool === s.tool && o.question === s.question
  );
  return match ? { ...match, ...s, _optimistic: false } : s;
});
```

Server fields overlay the optimistic entry; same key, same DOM node,
just a colour transition.

### 2 · Writeback spinner for stale optimistics

Optimistic entries older than 5s show an amber `animate-spin` ring
instead of the cyan "● new" badge. Signals "writeback might be slow"
to the operator without being alarming (amber, not red).

Drive: a 1s `setInterval` ticks `now` on the trajectoryList Alpine
scope. `isStale(entry)` computes `(this.now - entry.timestamp_s) > 5`.
Cleaned up on `destroy()`.

### 3 · Orphan optimistics still bubble up

Optimistics whose server match hasn't landed yet (writeback in
flight) still render at the top, unchanged from v4.0.0a4. The
spinner now visually distinguishes "wrote ago, still confirming"
from "just wrote, server fast".

## Real numbers

- 1/1 v5.0.0a3-retro action item shipped
- 0 PRs opened — merged via `git merge --no-ff`
- 4 new unit tests (content-tuple key, spinner element, tick init,
  in-place reconciliation)
- Test suite delta: 688 + 2 skips → **692 + 2 skips**
- `mypy --strict` clean across 49 source files
- `ruff` clean across `src/` and `tests/`
- 0 backwards-incompatible changes — pure rendering polish

## What worked

- **Content-tuple key, not synthetic id.** A naive cross-fade with
  `:key="t.id"` would always remount on optimistic→real swap (id
  changes from `optimistic-1715260000` to a sqlite rowid). Keying on
  `(project, tool, question)` keeps the DOM stable so the CSS
  transition can play.
- **Tailwind transition-colors handles the fade.** No `x-transition`,
  no JS animation logic — just one class on the `<li>` and the
  browser does the work. 4 lines of CSS power the whole effect.
- **`init()` + `destroy()` lifecycle.** Alpine's component lifecycle
  hooks are exactly what this needs; the 1s tick is created on mount
  and torn down on unmount. Memory hygiene, no leaks.
- **5s threshold matches operator perception.** Under 5s feels
  "instant"; over 5s feels "is something stuck?". The spinner only
  appearing past that line surfaces real issues without crying wolf.

## What to change / next

- **No "stuck for >30s" escalation.** A truly hung writeback shows
  the same amber spinner forever. A future tier could flip to red
  + "writeback failed" after 60s. Defer until observed.
- **5s threshold isn't configurable.** Hardcoded in `isStale`.
  Operators with very slow networks might want a higher threshold.
  Defer — adjust in code if needed.

## Action items for the next sprint (v5.0.0a5)

1. **Graph zoom UX polish.** Add double-tap-to-reset on touch
   (mobile equivalent of the desktop reset button) and keyboard
   shortcuts on desktop (`+` / `-` zoom, arrows pan, `Escape` reset).

## Out-of-scope (still)

- Tauri / Electron desktop UI — no demand.
- Relay-binary path (Path B) — Path C HTTP tunnel covers it.
- IDE extension — MCP works with any MCP client.
- Session-cookie auth + CSRF — defer until multi-operator UI is real.
- pnpm v5 lockfile support — pre-2022 format.
- Manual "trigger reembed now" button — defer until needed.
- Reembed ETA estimation — defer until rate signal stabilises.
- delegate_task stress coverage — defer until safety map differentiates.
- Streaming-chunks stress — defer until streaming path bottlenecks.
- Config-driven safety allowlist — keep code-controlled by design.
- CLI dispatcher-status command — defer.
- Stuck-writeback escalation tier — defer until observed.
- Configurable stale threshold — defer until needed.

# Sprint Retro — Harbormaster v19.0.0a7

**Date:** 2026-05-11
**Theme:** Phase 7 of the v19.0 workspace redesign — real-time activity
feed via SSE in the inspector pane. Closes the polling-only gap left by
v19.0.0a3: the inspector's `Recent activity` widget now subscribes to
`/api/network/stream` for live MCP-call updates while keeping the 10s
poll path as a graceful fallback. **Final phase before GA.**

## What shipped

- **`activityFeed()` factory in `dashboard.html`** extended with an
  EventSource subscription against `/api/network/stream`. Same SSE
  pattern as `network.html` (cookie-auth EventSource — no custom
  headers, see v15 notes). Initial `/api/network/events?limit=10`
  fetch + 10s poll **kept** as a fallback for proxy environments
  where SSE upgrades are stripped.

- **1s flush bucket.** Live events arrive into a `_buffered` array and
  drain into `this.events` once per second via `_flushIntervalMs:
  1000`. Avoids reflow thrash during call bursts (e.g. fan_out across
  10 projects firing back-to-back).

- **Pulse animation.** Newly-prepended rows wear `_new=true` for
  `_flashHoldMs: 1500` ms, which the template translates to
  `animate-pulse text-accent` (Tailwind built-in — no custom CSS).
  After 1.5s a single `setTimeout` callback flips `_new=false` for
  every row, returning them to the muted resting style. This trades
  one extra map() pass per flash for a single timer instead of N
  per-row timers.

- **Live indicator.** A small `●` next to `Recent activity` in the
  inspector header, bound to `connected` (toggled by EventSource's
  `open`/`error` handlers). Operator can see at a glance whether the
  stream is live versus stalled in poll-only fallback. Hidden by
  default until the first `open` event so it doesn't claim "live"
  during the connecting handshake.

- **Dedup on flush.** `_flush()` builds a Set of
  `(timestamp_ms+tool+target)` keys from incoming events and filters
  the existing `events` array through it. Without this, the brief
  overlap window between the initial REST fetch and the first SSE
  delivery could render duplicate rows for the same call.

- **Cap at 10 events.** Same number as the inspector's initial fetch
  limit — keeps the inspector tail short and prevents unbounded
  memory growth on a long-running session.

- **`view all →` link** added below the feed pointing at `/network`.
  Filled in a small UX gap left from a3 — the inspector tail had no
  drill-in path to the full log.

- **`destroy()` teardown.** Closes the EventSource and clears all
  three timers (`_interval`, `_flushInterval`, `_clearFlashTimer`).
  Wired to `x-on:beforeunload.window` so SPA-style navigation
  doesn't leak EventSource handles or background flushers.

## Tests added

`tests/ui/test_v19_inspector_activity_sse.py` — 7 source-only
assertions following the same pattern as `test_v19_inspector_content.py`.
Locks the contract for: `subscribe()` wired in `x-init`, live indicator
present + bound to `connected`, `view all` link to `/network`, pulse
class bound to `_new`, factory contains EventSource against
`/api/network/stream` + 1s flush + 1.5s flash-clear + 10-event cap +
`destroy()`, initial-load endpoint preserved, dedup logic in `_flush()`.

Behavioural integration is exercised by the visual-verification
script (`/tmp/v19a7_verify2.py`) during release: confirms EventSource
opens, `connected` flips true, live indicator becomes visible, and
both initial REST + SSE requests fire.

## Test count

- Pre-a7: 1731
- Post-a7: 1738 (+7 from `test_v19_inspector_activity_sse.py`)

## Coordination notes

- Phase 6 (`feat/v19.0-memories-editor`, a6) was running in parallel
  on the operator's machine. Its branch swaps repeatedly clobbered
  the working tree mid-edit. Mitigation that worked: re-apply edits
  on a clean branch from `main`, then **commit + push to origin
  immediately** before any verification step. Pushing first protected
  against the next branch swap deleting uncommitted work.

- a6 hadn't merged into `main` at the time of this ship, so a7 was
  cut from `19.0.0a5` directly. The version sequence on `main`
  becomes `a5 → a7` if a6 merges later (no `a6` tag on the trunk
  unless Phase 6 catches up).

## Why these design choices

- **Reuse the proven network.html SSE pattern.** `network.html` has
  shipped the same EventSource → cookie-auth → `addEventListener('event', ...)`
  flow since v15.0.0a1. Forking a different pattern in the inspector
  would multiply the surface area for SSE bugs.

- **Keep the 10s poll fallback.** Cheap insurance. Removing it would
  have saved ~12 LOC and broken any deployment behind an SSE-stripping
  reverse proxy.

- **Single setTimeout for the flash, not per-row.** The original spec
  hinted at per-row timers; rejected because 10 timers per burst would
  thrash with no visible benefit (all events flash for the same
  duration anyway).

- **Tailwind `animate-pulse` over a custom keyframe.** Built-in,
  exactly the right cadence for "this just arrived," no CSS edits to
  the global stylesheet.

## Files modified

- `src/harbormaster/ui/templates/dashboard.html` — inspector activity
  section (HTML) + `activityFeed()` factory (JS).
- `tests/ui/test_v19_inspector_activity_sse.py` — new (7 tests).
- `src/harbormaster/__init__.py` — version bump 19.0.0a5 → 19.0.0a7.
- `docs/sprint-retro-harbormaster-v19.0.0a7.md` — this file.

## Untouched (per concurrency guard)

- `project_detail.html` — Phase 6 territory.
- `_partials/_memory_*.html` — Phase 6 territory.
- `tests/ui/test_v19_memories_tab.py` — Phase 6 territory.
- `.github/workflows/*` — out of scope.

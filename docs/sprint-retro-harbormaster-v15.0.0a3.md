# Sprint Retro — Harbormaster v15.0.0a3

**Date:** 2026-05-10
**Theme:** Live-refresh polish — SSE-driven timeline + dropdown.

## What shipped

- **Timeline view: SSE-driven live refresh** (v14 candidate #7): the
  v14.a4 timeline used a getter that recomputed all 60 buckets on
  every Alpine reactive read. SSE bursts (events.push per event)
  triggered a re-evaluation each push — O(N×60) under load. Phase 3
  introduces a bucket cache invalidated by:
    1. window change (1h ↔ 24h),
    2. events.length growth AND cache stamp >1s,
    3. periodic 1s `_timelineTick` bumper (drives Alpine to re-evaluate).
  Bars still update in real time but at most once per second.
- **Network filter dropdown live-refresh** (v14 candidate #12): the
  SSE `event` handler now calls `_maybeAppendSourceOption(ev)` —
  Set-based dedup, sorted insertion. New `caller` values appear in
  the dropdown without page reload, closing the v14.a2 staleness gap.

## Numbers

- **Tests**: 1457 → 1468 (+11)
- **Source files**: 57 (no change — pure template extension)
- **Wall-clock**: ~20 min
- **Commits on main**: 1 feature merge
- **Lint / type**: ruff clean, `mypy --strict` clean
- **Backwards-incompatible changes**: 0

## What worked

- **Cache-with-tick pattern.** The Alpine "reactive read" pattern
  meant the simplest live-refresh wiring is: cache aggressively, bump
  a tick variable on a timer, have the getter touch the tick to
  declare a dep. Re-renders happen exactly once per second regardless
  of SSE event burst rate.
- **Set-based dedup over array `.includes`.** O(1) lookup avoids the
  pathological case of "many duplicate caller events in a 100ms
  window each triggering a 50-element array scan."
- **Behavioural carry-over guard.** A test asserts the v11.0.0a6
  `chatOrder` cache fields still exist — guards against accidentally
  removing the older cache while adding the newer timeline cache.

## What to change

- **Throttle could become a global Alpine pattern.** `_chatOrderCache`
  uses length-based invalidation; `_timelineCache` uses time-based.
  A future v15+ candidate: extract a `cachedGetter(deps, ttl_ms)`
  helper used by both. (Not v15-scope; flagged for v16.)

## Next phase (v15.0.0a4)

- N-way reembed run comparison (up to 4)
- Per-tool budget alongside per-host

## Halt assessment

- 7 v14 candidates remain; v15.0.0a3 closes 2 more (7 total of 12).
- Test suite green, lint clean, no breaking changes — release bar met.
- **Continue.**

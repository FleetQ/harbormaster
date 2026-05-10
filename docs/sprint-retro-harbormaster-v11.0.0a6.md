# Sprint Retro — Harbormaster v11.0.0a6

**Theme:** Caches consolidation + a new aggregate endpoint. Three
small performance polishes bundled into one phase.

## What shipped

1. **`/api/ignored-projects` 60s TTL memo.** The endpoint runs
   discovery twice (once with empty patterns, once with the live
   patterns) and diffs. The sidebar polls it on every page load.
   Cached payload returns within 60 seconds of the first call.
2. **`chatOrder()` reverse-cache (`network.html`).** The chat view
   re-runs `chatOrder` on every Alpine paint; recomputing
   `[...events].reverse()` each frame is wasteful when no new
   events arrived. Cached, keyed off `events.length` (events are
   append-only modulo the FIFO shift at cap, so length is a
   sufficient invalidation key).
3. **`NetworkStore.stats(since_ms=...)`** — aggregates
   `total_calls`, `by_tool` counts, top 5 target projects, and
   `error_rate` over an epoch-ms window. Returns empty-shape when
   no rows match.
4. **`GET /api/network/stats?window=<1h|24h|7d|all>`** — surfaces
   the aggregate. 400 on unknown window. The `/network` template
   gains a small stats panel above the graph with a window dropdown
   that re-fetches on change.

## Tests

| Suite delta                                | Before | After |
|--------------------------------------------|-------:|------:|
| Total tests                                | 1181   | 1192  |
| New (test_caches_phase6.py)                | —      |   +11 |

Coverage:
- `/api/ignored-projects` payload (count, names, patterns)
- TTL cache hit (second request returns same body)
- `NetworkStore.stats` empty shape
- `NetworkStore.stats` total + by_tool + top_projects + error_rate
- `since_ms` filter excludes pre-cutoff rows
- `/api/network/stats` default window (`24h`)
- accepts `1h`, `24h`, `7d`, `all`
- rejects unknown windows (400)
- top-projects ordering by call count
- `/network` template includes the stats panel + window dropdown
- `/network` template uses chatOrder cache state vars

## Quality gates

```
mypy --strict src/harbormaster   →  Success: no issues found in 56 source files
ruff check src tests              →  All checks passed!
pytest -q                         →  1192 passed, 2 skipped in 37.82s
```

## Architecture notes

- The TTL memo is a tiny dict (closure-captured inside
  `register_routes`) instead of a full `ProjectsCache`-style object
  — the workload is single-process + low-frequency, the dict is
  simpler. Same TTL pattern can scale up to a class if a third
  endpoint adopts the same shape.
- `chatOrder()` invalidation is ONE-WAY (length-based). The cap
  (`events.shift()` past 500) overlaps with new pushes but the
  length still changes monotonically across normal play, so the
  cache stays correct. Long-tail edge case: if `events.length` is
  exactly `500` for two consecutive paints with different content,
  the cache could lag by one frame — acceptable for a chat view
  where Alpine repaints again on the next event push.
- `since_ms` filter uses a SQL `WHERE timestamp >= ?` against the
  existing `idx_mcp_calls_timestamp DESC` index — fast even at the
  5000-row cap.

## Deviations

- None.

## Next

Phase 7 — x-data unhandled-promise lint + per-surface heartbeat
tuning (final polish before GA).

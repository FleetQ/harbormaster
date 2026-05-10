# Sprint Retro — Harbormaster v17.0.0a1

**Date:** 2026-05-10
**Theme:** Trace waterfall renderer — closes v16.a6 split + the
8-version-old carry-over since v9.0.0a3 ("trace waterfall surface").

## What shipped

- `/dispatcher` "Recent traces" section now groups completed spans
  by `trace_id`, sorted newest-first by root `started_at`.
- Each trace renders as a collapsible card; trace header is a
  button with `aria-expanded` / @click toggling `trace.collapsed`.
- Inside a trace, spans render as nested rows indented by depth
  (parent walk capped at 8 levels). Each row shows
  `[start_ms—end_ms] tool (status)`, a relative-position bar
  (offset + width computed from `barOffsetPct` / `barWidthPct`
  against the trace window), and `duration_ms`.
- Per-span +/- toggle expands an attribute panel
  (`span_id`, parent, trace, project, started, ended). The
  toggle button carries a dynamic `:aria-label` per the
  a11y floor contract.
- SSE `span_end` events append to the matching trace via
  `_appendCompleted` → `_buildTrace` re-derives depth + sort
  order. New traces appear at the top, capped at 100 to mirror
  the server ring buffer.
- "In-flight" section preserved verbatim from v9.0.0a3 — live
  indicator + per-span duration label keep working.

## Non-changes (deliberate)

- Backend wire format untouched — v16.a6 already emits
  `parent_span_id` + `trace_id` on every span_start / span_end.
- `/api/dispatcher/recent` shape untouched — already includes
  the hierarchy fields since v16.a6.
- The `traceWaterfall()` Alpine factory name preserved (the
  v9.0.0a3 dispatcher page test pinned it).

## Tests added

`tests/ui/test_v17_trace_waterfall_renderer.py` — 8 tests:

1. `test_waterfall_markup_present` — data-trace-waterfall-list,
   data-trace-toggle, data-trace-spans, data-span-toggle,
   data-span-attributes, data-depth, "Recent traces" header,
   "In-flight" preserved.
2. `test_waterfall_factory_preserved` — `traceWaterfall()` name.
3. `test_waterfall_helpers_present` — barOffsetPct, barWidthPct,
   traceDurationMs, formatRel, _groupIntoTraces, _buildTrace,
   _appendCompleted.
4. `test_waterfall_keeps_sse_endpoints` — `/api/dispatcher/trace`
   + `/api/dispatcher/recent` still wired.
5. `test_recent_endpoint_carries_hierarchy_for_renderer` —
   end-to-end: parent dispatch + child via `span_context` lands
   in `/api/dispatcher/recent` with parent_span_id + trace_id
   correctly populated.
6. `test_real_dispatch_lands_with_trace_id` — sanity: real
   `MCPDispatcher.dispatch` flow populates trace_id.
7. `test_collapse_toggle_on_trace_header` — Alpine
   `trace.collapsed = !trace.collapsed`, x-show, aria-expanded.
8. `test_expand_toggle_on_span_attributes` — same for
   `span.expanded`.

## Numbers

- Tests: 1593 → 1601 (+8)
- Source files: 57 → 57 (template-only change)
- mypy --strict + ruff: clean
- Backwards-incompatible changes: 0
- Wall-clock: ~25 min
- CWD discipline lapses: 0
- Did NOT touch `.github/workflows/*`: yes

## What worked

- **Backend already shipped the hard part.** v16.a6's
  `parent_span_id` + `trace_id` propagation + `_lookup_trace_id_locked`
  meant the renderer just had to consume well-shaped events; zero
  schema work in this phase.
- **Pinning data-* hooks.** The new tests assert on
  `data-trace-toggle` / `data-span-toggle` / `data-span-attributes`
  rather than CSS classes, so future style refactors won't break
  the contract.
- **A11y floor caught the icon-only span toggle.** The first test
  pass surfaced one missing aria-label; the existing
  `test_a11y_floor.py` audit forced the dynamic
  `:aria-label="span.expanded ? 'Hide' : 'Show'"` shape.

## v17 carry-overs (next phases)

2. **Codex backend tool_use instrumentation parity** — phase 2.
3. **N-way reembed compare UI + sparkline integration** — phase 3.
4. **`tightest_cap` KPI hover tooltip** — phase 4.

## Halt assessment

5 candidates remain after this phase. Continue per operator
"continue indefinitely while ≥1 candidate exists" invariant.

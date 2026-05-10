# Sprint Retro — Harbormaster v18.0.0a2

**Date:** 2026-05-10
**Theme:** Trace waterfall hover/focus tooltip — final cosmetic
polish item from the v17 candidate list.

## What shipped

- New tooltip on each span row in the dispatcher trace waterfall
  (`/dispatcher` → "Recent traces" section).
- Reveal driven by Tailwind utility classes only (no new tooltip
  library): the row is a `group` with `relative` positioning, the
  tooltip is `hidden group-hover:block group-focus-within:block`,
  positioned `absolute left-8 top-full mt-1`.
- Tooltip element carries `role="tooltip"`, a deterministic
  `id="span-tip-${span.span_id}"`, and the row carries the matching
  `aria-describedby` binding — so screen readers announce the
  summary when the row receives focus.
- Row is `tabindex="0"` so keyboard users can tab to it; the
  reveal then fires via `group-focus-within`.
- Tooltip text is computed by a new factory helper
  `spanTooltipSummary(span)` that returns
  `"<tool> | <duration_ms>ms | <ok|error> | project=<v> | span_id=<v>"`.
  Centralizing the format in the helper means tests pin the
  string in JS, not the template.

## Format choice — the "first 2 attribute key-value pairs"

The dispatcher span shape (`MCPDispatcher`) does not carry a
separate `attributes` map — it carries fixed fields (`tool`,
`project`, `span_id`, `trace_id`, `parent_span_id`, `started_at`,
`ended_at`, `duration_ms`, `ok`). The tooltip's "first 2 attribute
key-value pairs" therefore use the same first two non-trivial
fields the existing expanded panel surfaces: `project` and
`span_id`. This keeps the change minimal — no schema change, no
new SSE event payload — and the hover summary stays consistent
with the click-to-expand panel below it.

## Non-changes (deliberate)

- Existing expand/collapse `+/−` button preserved.
- Existing inline `[start_ms—end_ms] tool` summary preserved.
- Existing per-span `:aria-label` on the bar preserved.
- Active span list (`In-flight` section) untouched — tooltip is
  for the completed-trace waterfall only.
- Span data shape unchanged (no new fields requested from the
  dispatcher; helper reads only what's already there).

## Tests added

`tests/ui/test_v18_trace_waterfall_hover_tooltip.py` — 5 tests:

1. `test_tooltip_element_present` — `data-span-tooltip` and
   `role="tooltip"` markup.
2. `test_tooltip_aria_describedby_link` — row's
   `:aria-describedby` and tooltip's `:id` use the matching
   `span-tip-${span_id}` template.
3. `test_tooltip_keyboard_reachable` — `tabindex="0"` on the row,
   `group-focus-within:block` and `group-hover:block` reveal
   classes both present.
4. `test_tooltip_summary_helper_exists` — Alpine binding calls
   `spanTooltipSummary(span)`, helper defines `duration_ms`,
   `ok ? 'ok' : 'error'`, and the two attribute pairs.
5. `test_tooltip_does_not_introduce_new_dependency` — sanity
   check that no new tooltip lib (`tippy`, `popperjs`,
   `floating-ui`) was added.

## Numbers

- Files touched: 1 template (`dispatcher_trace.html`,
  +30 lines net).
- New tests: 5.
- Test count: 1629 → 1634.
- Source files: 57 → 57 (template-only change).
- Lint + mypy --strict: clean.
- Wall-clock from worktree creation to retro: ~12 minutes.

## What's next (v18.0.0 GA)

GA closes both phases (autobootstrap CI workflow + tooltip) and
publishes the cumulative chain-close retro for v9 → v18. After GA
tag, the autonomous chain HALTS — 0 candidates remain.

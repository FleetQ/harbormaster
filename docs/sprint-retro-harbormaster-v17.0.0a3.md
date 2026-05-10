# Sprint Retro — Harbormaster v17.0.0a3

**Date:** 2026-05-10
**Theme:** N-way reembed compare UI + sparkline integration —
closes two v16 carry-overs in one phase.

## What shipped

### Multi-select reembed compare (carry-over #4)

- New checkbox column on the v7.0.0a4 reembed history table
  (left-most). Clicking toggles the row's absolute index in/out
  of the selection.
- Selection capped at 4 (matches the server cap on
  `/api/history/reembed/runs/compare`). Disabled checkboxes give
  the user immediate feedback at the cap.
- Compare action bar appears once ≥1 selected; "Compare selected"
  enables at ≥2; "Clear" empties.
- Comparison panel renders side-by-side via Alpine x-for:
  - One row per field record `{name, values}`.
  - One column per selected run (header shows `#<absolute-index>`).
  - Numeric formatter for `duration_seconds`; em-dash for missing.

### sparklineHtml integration (carry-over #3)

- Comparison panel's trailing column renders a sparkline trend
  per row via `sparklineCell(field)`:
  - Numeric fields (`duration_seconds`, `total`, `succeeded`,
    `failed`, `cancelled`) render an SVG sparkline at 60×14
    via the global `window.sparklineHtml` helper from
    `_partials/_tiny_sparkline.html` (loaded by base.html).
  - Non-numeric fields (`model`) render an em-dash.

## Non-changes (deliberate)

- The v15.a4 endpoint shape untouched — already returns `{indices,
  runs, fields}` with the right `{name, values}` field shape.
- `_tiny_sparkline.html` partial untouched — first consumer of an
  unchanged helper.
- `slice(-5).reverse()` display shape on the table preserved —
  v17.a3 only adds a column + a panel.
- The v14.a3 per-row Diff button + diff panel preserved.

## Tests added

`tests/ui/test_v17_reembed_compare_sparkline.py` — 9 tests:

1. `test_compare_action_bar_markup` — `data-reembed-compare-bar`,
   `data-reembed-compare-trigger`, `data-reembed-compare-checkbox`.
2. `test_compare_panel_markup` — `data-reembed-compare-panel`,
   `data-reembed-compare-table`, `data-reembed-compare-sparkline`.
3. `test_compare_panel_consumes_v15_endpoint` — pins
   `/api/history/reembed/runs/compare` URL.
4. `test_sparkline_helper_loaded_globally` — pins `sparklineHtml`
   + `sparklineCell` references in dashboard render.
5. `test_compare_factory_state_initialised` — `selectedRunIndices`,
   `compareOpen`, `compareLoading`, `compareData`.
6. `test_compare_helper_functions_exist` — toggle, clear,
   loadCompareSelected, formatCompareCell, sparklineCell.
7. `test_compare_caps_at_4` — cap check in toggle handler body.
8. `test_compare_endpoint_shape_for_renderer` — wire-shape
   regression guard with monkeypatched runs.
9. `test_compare_endpoint_caps_at_4` — server-side cap mirrors
   UI cap.

## Numbers

- Tests: 1612 → 1621 (+9)
- Source files: 57 → 57 (template-only change)
- mypy --strict + ruff: clean
- Backwards-incompatible changes: 0
- Wall-clock: ~30 min (includes one Edit-tool resolved-to-parent
  detour — see "What surprised us" below)
- CWD discipline lapses: 1 (Edit tool resolved absolute worktree
  paths to the parent checkout for dashboard.html; recovered by
  copying the parent's working-copy edits into the worktree
  before commit).
- Did NOT touch `.github/workflows/*`: yes

## What surprised us

The Edit tool, given an absolute path inside the worktree
(`.claude/worktrees/agent-…/src/harbormaster/ui/templates/dashboard.html`),
appears to have applied the change to the parent checkout's
copy of the same logical path. The git index in both checkouts
saw a "M dashboard.html" against parent's HEAD, not the
worktree's branch HEAD. Recovery: cp the parent file into the
worktree, `git checkout --` the parent, then commit on the
worktree branch.

This wasn't a CWD-discipline lapse in the binding-lessons sense
(no `cd` was run); it's a tooling quirk worth flagging for the
v17 retro chain. v17.a4 will stage the same way and watch for it.

## What worked

- **Mirror, don't invent.** The compare panel mirrors the v14.a3
  diff panel structure; the per-row checkbox mirrors a hundred
  prior `<td><input type="checkbox">` patterns. Nothing new
  designed.
- **Endpoint already shape-stable.** `/api/history/reembed/runs/compare`
  returns `{indices, runs, fields: [{name, values}, ...]}` —
  the renderer consumes that 1:1 with no transformation.
- **sparklineHtml helper was already global.** Loaded once in
  base.html (v16.a4) so the dashboard's `sparklineCell` just
  calls `window.sparklineHtml(values, opts)` and mounts the
  returned SVG via `x-html`.

## v17 carry-overs (next phases)

4. **`tightest_cap` KPI hover tooltip** — phase 4.

## Halt assessment

After v17.a3, only **3 candidates** remain (#5 phase 4 +
#1 operator-blocked CI work + #6 codex tool_use observation
for non-instrumented `_helpers.py` paths — but #6 was
implicitly addressed by v17.a2's line-level dispatcher that
fires on every codex stream line). Realistically v17.a4 + GA
may close the chain unless v18 candidates surface. Continue
per operator "continue indefinitely while ≥1 candidate exists"
invariant.

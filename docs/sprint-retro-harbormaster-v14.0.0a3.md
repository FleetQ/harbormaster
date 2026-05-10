# Sprint Retro — Harbormaster v14.0.0a3

**Date:** 2026-05-10
**Theme:** Two diff-UI surfaces consuming v13.a3 server endpoints —
memory editor side-by-side toggle + reembed history row diff.

## What landed

### `harbormaster` (this repo)

| SHA | Subject |
|-----|---------|
| `85731f0` | feat(v14.0.0a3): HTML diff toggle + reembed-row diff button |

## Capabilities (this sprint)

### 1 · Memory editor: Unified / Side-by-side diff toggle

The memory editor's diff panel (project_detail.html) grows two
toggle buttons. The default `Unified` calls
`/api/projects/{name}/memory-revisions/diff?from=N&file=…` with no
`format` param and renders the unified text into a `<pre>` (existing
v12.a4 path). The new `Side-by-side` button calls the same endpoint
with `format=html` and renders the v13.a3 `difflib.HtmlDiff().make_table`
table inline via `x-html`.

The server already sanitises the HtmlDiff output (see v13.a3 retro);
we additionally constrain the rendering container to `max-h-64
overflow-auto` for visual parity with the unified pane.

### 2 · Reembed history table: per-row Diff button

Every row in the reembed history table on the dashboard grows a
small `Diff` button (hidden on the chronologically-first row, which
has nothing to compare against). Clicking opens an inline panel that
calls `/api/history/reembed/runs/diff?from=N-1&to=N` and renders the
v13.a3 delta payload — `duration_seconds`, `total`, `succeeded`,
`failed`, `cancelled`, `model_changed` — as a 6-cell DL.

Sign-prefixed deltas (`+5` / `-3`) and contextual colors:

* `succeeded` < 0 → red (regressed)
* `failed` > 0 → red (regressed)
* `cancelled` > 0 → yellow
* `model_changed = true` → yellow

A single shared `runDiff` slot means only one diff is visible at a
time — clicking another row replaces the panel. A `close` button
collapses it.

## Real numbers

- 2/2 v14.a2 sprint-plan items shipped (memory diff toggle + reembed row diff)
- 1 commit, 4 files changed (2 templates, 2 tests)
- 9 new template-smoke tests in `tests/ui/test_v14_diff_ui_wiring.py`
- 1 existing test fixed up to reflect the v14.a2 ${BRANCH} braced form
  (`test_wt_merge_script_uses_no_ff_merge_format`)
- Test suite delta: 1375 → 1384 passed
- Lint: ruff clean. Type-check: `mypy --strict` clean (57 source files)
- Backwards-incompatible changes: 0

## What worked

- **Template smoke tests over Playwright for thin UI changes.** Both
  surfaces are pure JS/HTML wiring on top of existing server
  endpoints. Asserting that the template contains `loadRunDiff(r)`,
  `format=html`, `runDiff.delta?.succeeded` etc. catches 95% of
  "did the wiring drop" regressions in 200ms — vs spinning up a real
  browser.
- **Reusing v13.a3 endpoint shape.** The reembed parity payload
  already contained every field needed for the panel rendering
  (`duration_seconds`, signed integer deltas, `model_changed`).
  Zero new server work; the entire phase landed in templates.
- **`indexOf(r) > 0` to hide the first-row Diff button.** Cleaner
  than threading an `index` through the iteration; Alpine's `runs`
  array is the source of truth and `indexOf` is O(N) but N=5
  (the table is sliced).

## What to change / next

- **The reembed `runs` array is reverse-rendered for display but
  stored chronologically-ascending.** The `loadRunDiff` logic
  exploits this (`idx > 0` means "has a prior chronological run"),
  but a future contributor refactoring the table iteration into
  reverse-storage would silently break the diff direction. Add a
  comment + maybe a unit assertion if the storage order changes.
- **Single-row diff panel state is shared.** If two operators want
  to compare run #2-vs-#3 *and* run #4-vs-#5 simultaneously, the
  single `runDiff` slot collides. YAGNI for now (one operator per
  dashboard) — but log this if it ever bites.

## Action items for the next sprint (v14.0.0a4)

1. **Per-host token budget visibility.** Extend `[hosts.*]` config
   with `daily_token_budget = 100000` (optional). New endpoint
   `GET /api/hosts/budget` returns per-host token consumption (last
   24h from QAStore) vs budget. KPI strip (v8.a5) gains a budget-
   usage % cell per host.
2. **Network event timeline graph.** Add a horizontal-bar timeline
   view to `/network` showing event density over the last 1h / 24h.
   Toggle button: Graph / Chat / Timeline (3-way switch).

## Out-of-scope (still)

- N-way reembed run comparisons (only 2-way `from`/`to` ships).
- Sticky diff panel that survives row re-render — small UX win, not
  worth the state-management complexity.
- Inline highlight of diff hot-rows in the side-by-side memory diff —
  HtmlDiff already classes changed cells; could style via CSS, but
  current cyan-on-gray is readable enough.

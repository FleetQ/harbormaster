# Sprint Retro — Harbormaster v19.0.0a5

**Date:** 2026-05-11
**Theme:** Phase 5 of the v19.0 workspace redesign — dashboard
re-layout for the new three-column shell. Quick Ask card promoted to
the top of the main pane; widget cards flow in a 2-column responsive
grid; KPI strip kept as the at-a-glance row between them. Closes the
gap between the new shell (a1–a3) + new tokens (a4) and the actual
operator surface — until a5 the dashboard body still rendered as a
single tall stack of full-width sections.

## What shipped

- **Quick Ask card** at the top of `dashboard.html`'s
  `{% block content %}`. Renders above the KPI strip with a project
  picker, question input, and an `Ask →` button. Cmd-K hint visible
  in the header.
  - Project list pulled from `/api/projects` on `init()`.
  - Submit handler navigates to
    `/projects/{name}?q={question}` — the project page already wires
    `_partials/_ask_form_script.html`'s `askForm()` factory, which
    honours the `?q=` URL pre-fill via its own `init()` (added in
    v11.0.0a4 for the cmd-K palette). The dashboard hands off via
    URL rather than duplicating the SSE plumbing.
  - **Why navigation, not inline SSE?** The spec called this out as
    an acceptable pragmatic fallback. The dashboard already mounts six
    Alpine factories (`kpiStrip`, `statusStrip`, `recallPanel`,
    `graphPanel`, `projectGrid`, `reembedPanel`) plus the v19.0.0a3
    inspector pair (`kpiInspector`, `activityFeed`). Adding a seventh
    streaming factory would have ~80 LOC of new SSE event-handling
    state to maintain and would violate the "single source of truth"
    spirit — the project page already streams. URL handoff costs one
    full-page navigation but reuses 165 LOC of existing partial.

- **Card grid wrapper**
  (`<div class="grid grid-cols-1 md:grid-cols-2 gap-3 mb-4" data-card-grid>`)
  wraps every dashboard widget BELOW the KPI strip and ABOVE the
  project grid. Wide widgets (`statusStrip`, `reembedPanel`,
  `recallPanel`, `graphPanel`) keep their existing horizontal layouts
  by carrying `md:col-span-2`. The new `recentActivityCard` lives
  alongside them as a 1-column card.

- **Recent activity card** (`recentActivityCard()` Alpine factory) —
  same shape as the v19.0.0a3 inspector `activityFeed`, sharing the
  `/api/network/events?limit=10` endpoint and the 10s auto-refresh
  interval. Mirrored on purpose: operators who collapse the inspector
  still see recent activity at a glance.

- **KPI strip** unchanged structurally. The
  `data-tour-step="kpi-strip"` hook moved up from a child KPI cell to
  the section root so the v19 dashboard tour still anchors correctly
  (it pointed at the same cell either way; this is just cleaner).

- **Project grid** (long scrollable list) preserved in its existing
  position **below** the card grid — the card grid is the new "above
  the fold" surface; the project grid is the long browser below.

## Test deltas

- 1719 → 1731 collected (+12 new tests in
  `tests/ui/test_v19_dashboard_relayout.py`):
  - Quick Ask card position relative to KPI strip (`{% block content %}`
    bounds check).
  - `quickAsk()` factory presence + `/api/projects` source +
    `/projects/{name}?q=...` navigation handoff.
  - Quick Ask form fields (project select, question input, submit).
  - Quick Ask uses real Tailwind v4 tokens (regression check from
    inspector a2 lesson — `border-muted` etc. don't exist).
  - KPI strip preserves its `lg:grid-cols-6` shape + tour anchor.
  - Card grid wrapper signature + closing comment present.
  - Card grid contains all 5 expected sections.
  - Wide widgets carry `md:col-span-2`.
  - `recentActivityCard()` factory mirrors inspector (same endpoint,
    same `setInterval` convention).
  - Recent activity card links to `/network`.
  - All existing factories still mounted (regression).
  - Project grid renders below the card grid close.

- All 727 UI tests pass (excluding pre-existing playwright flake in
  `test_v19_three_column_shell.py::test_inspector_collapse_hides_panel_and_persists`
  — confirmed pre-existing on `main` before my change; tour overlay
  intercepts the click, unrelated to the re-layout).
- mypy `--strict` clean.
- ruff clean.

## Files modified

- `src/harbormaster/ui/templates/dashboard.html` — restructured
  `{% block content %}`: Quick Ask added on top, KPI strip kept,
  widget sections wrapped in card grid, wide widgets gain
  `md:col-span-2`, project grid pinned below the close. Two new
  Alpine factories (`quickAsk`, `recentActivityCard`) added to the
  existing dashboard `<script>` block.
- `src/harbormaster/ui/static/tailwind.css` — recompiled via
  `npx @tailwindcss/cli` against the unchanged `tailwind.input.css`
  + the updated `dashboard.html`. New utilities pulled in:
  `flex-1`, `md:flex-row`, `md:w-56`, plus `data-quick-ask` /
  `data-card-grid` / `data-recent-activity-card` data attribute
  references (all already-existing tokens — no new `@theme` entries).
- `tests/ui/test_v19_dashboard_relayout.py` — new file with 12 source-
  level structural assertions following the
  `test_v19_inspector_content.py` pattern (no live server, no
  playwright).

## Lessons / gotchas

- **`build_tailwind_css.py` is a hatchling build hook, not a CLI.**
  Trying to invoke it directly hits `ModuleNotFoundError: hatchling`
  because the import is at module top. For ad-hoc dev rebuilds, the
  workflow is `npx --yes @tailwindcss/cli -i ... -o ...` from a temp
  directory with `tailwindcss` + `@tailwindcss/cli` installed; the
  `@source "../templates/**/*.html"` directive in `tailwind.input.css`
  resolves relative to the input file's directory, so pointing the
  temp build at the real templates needs a path rewrite. Captured
  here so the next phase that touches CSS doesn't re-discover this.
- **Arbitrary Tailwind v4 grid templates didn't pick up.** The first
  spec attempt used `grid-cols-[14rem_1fr_auto]` for the Quick Ask
  form. The v4 CLI did not emit that utility even with the template
  in scope (likely a parser quirk around the underscore-separated
  arbitrary value). Fell back to `flex flex-col md:flex-row` with
  `md:w-56` on the select + `flex-1` on the input — same visual
  result, all pre-existing utilities, zero CSS surprises. Lesson:
  prefer flex-with-fixed-width when the alternative is an arbitrary
  bracket expression.
- **Pre-existing `test_v19_three_column_shell.py` flake confirmed.**
  Stashed my changes and reran the failing test against clean `main` —
  same failure (tour overlay intercepts the inspector-collapse
  button's click). Not introduced by this phase. Should be fixed in a
  follow-up by either skipping the tour in the test fixture or
  bumping the click target's z-index above the tour backdrop.
- **Non-test bridge errors confirmed pre-existing.** `tests/unit/
  test_bridge.py` shows 16 ERROR (not FAIL) entries when the full
  suite runs — `Failed: ScopeMismatch`. Stash test confirms these are
  also pre-existing fixture-scope issues unrelated to dashboard work.

## Phase status

v19 phases shipped: a1 (three-column shell) → a2 (project tabs) →
a3 (inspector content) → a4 (violet tokens + compact density) → **a5
(dashboard re-layout — this phase).** v19.0 GA blocking work: none
identified — the next sprint can either freeze for v19.0 final or
move onto v20 scope.

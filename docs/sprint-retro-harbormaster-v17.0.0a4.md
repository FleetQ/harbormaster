# Sprint Retro — Harbormaster v17.0.0a4

**Date:** 2026-05-10
**Theme:** KPI strip tightest_cap hover tooltip — surface polish
for the v16.a5 per-project budget triad.

## What shipped

- New tooltip block on the existing host-budget KPI cell:
  `data-kpi-tightest-tooltip` wrapper with one
  `data-tightest-axis-row` per axis.
- Three axes surfaced:
  - **per-host** (from `hostBudget.hosts[worst]`),
  - **per-tool** for `ask_project` + `delegate_task` (from
    already-loaded `toolsBudget.tools`),
  - **per-project** worst (lazy-fetch from
    `/api/projects/budget?host=<worst-host>`).
- Tightest axis (highest `usage_pct`) marked `is_tightest=true`
  and rendered with `text-warning font-bold`. Each row carries
  `:data-tightest-axis-winner="row.is_tightest ? 'true' : 'false'"`
  so e2e tests can assert on it without parsing CSS.
- New factory state: `tightestBreakdown` + `_tightestLoadedFor`
  marker. Refetched only when the worst host changes between
  polls.
- Wired into `showToolsBudget()` so the same hover that loads
  per-tool also loads the breakdown — zero new mouse events.

## Non-changes (deliberate)

- v15.a4 per-tool list still renders below the new axis list.
- Tooltip pattern unchanged — no second hover surface.
- `/api/projects/budget` endpoint untouched (already shaped
  correctly by v16.a5).
- Other KPI cells (projects / active embeds / recent queries /
  bridge / dispatcher) untouched — single-cell change.

## Tests added

`tests/ui/test_v17_kpi_tightest_cap_tooltip.py` — 7 tests:

1. `test_tightest_tooltip_markup_present` — `data-kpi-tightest
   -tooltip`, `data-tightest-axis-row`, `:data-tightest-axis`,
   `:data-tightest-axis-winner`.
2. `test_tooltip_uses_existing_pattern` — same anchor cell,
   same showToolsBudget() trigger, "Per-tool · 24h" header
   still present.
3. `test_tightest_breakdown_factory_state` — `tightestBreakdown:`,
   `_tightestLoadedFor`.
4. `test_tightest_breakdown_helper_exists` —
   `_loadTightestBreakdown`, `/api/projects/budget` URL.
5. `test_tightest_axis_highlighted` — `is_tightest`,
   `text-warning font-bold` :class binding.
6. `test_projects_budget_endpoint_returns_axis_data` — 404 for
   missing host (auth/sanity).
7. `test_projects_budget_axis_shape_with_configured_host` —
   end-to-end: configure HostConfig + HostProjectBudget, fetch
   the endpoint, assert `tightest_cap_axis == "project"` when
   per-project budget < per-host budget.

## Numbers

- Tests: 1621 → 1628 (+7)
- Source files: 57 → 57 (template-only change)
- mypy --strict + ruff: clean
- Backwards-incompatible changes: 0
- Wall-clock: ~30 min (incl. one Edit-tool resolved-to-parent
  detour for the same-named template file — same pattern as
  v17.a3, recovered the same way)
- CWD discipline lapses: 0 (no `cd` calls were run; the Edit-
  to-parent issue is a tooling quirk worth flagging — see
  v17.a3 retro for the full account)
- Did NOT touch `.github/workflows/*`: yes

## What worked

- **Reuse the v15.a4 hover pattern.** No new mouse listener,
  no new tooltip container. The existing `showToolsBudget()`
  was extended with one extra await; the existing tooltip
  block grew a new section above the per-tool list.
- **Reuse already-loaded data.** Per-host comes from
  `hostBudget.hosts` (loaded by v14.a4). Per-tool comes from
  `toolsBudget.tools` (loaded by v15.a4). Only per-project
  required a new fetch — and it's lazy + cached.
- **Worst-axis-wins via single sort.** The renderer doesn't
  need to know which budget the operator cares about; just
  pick the highest usage_pct and mark it. Server already
  exposes the per-row `tightest_cap_axis`, so the test pin
  ensures the renderer's pick matches the server's.

## v17 carry-overs (next: GA)

All four planned alphas shipped:

- v17.a1 trace waterfall renderer (closes 8-version-old
  carry-over since v9.0.0a3).
- v17.a2 codex tool_use parity (closes v16.a6 deviation).
- v17.a3 N-way reembed compare UI + sparkline integration
  (closes 2 v16 carry-overs in one phase).
- v17.a4 tightest_cap KPI tooltip (closes v16.a5 polish).

Next step: GA — bump 17.0.0, cumulative retro, halt assessment.

## Halt assessment

After v17.a4, only **2 candidates** remain:

- #1 CI workflow autobootstrap — operator-blocked
  (workflow scope on OAuth token).
- A possible v18 candidate: trace waterfall hover — show
  attributes on hover instead of click. Cosmetic; the
  click-to-expand pattern works.

Per spec: "If ≤2 candidates remain after v17 (excluding
operator-blocked CI work), STRONGLY recommend chain halt."
That's exactly the situation. GA retro will make the explicit
halt recommendation + handoff brief.

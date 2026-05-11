# Sprint Retro — harbormaster v21.0.0a2

**Theme**: Q&A History tab gets a real surface; Settings gets an editable
per-project daily-call budget form. Two operator-visible stubs replaced
with functional UI + the API endpoints to back them.

## What shipped

- **Q&A History tab**: replaced the v19.0.0a5 placeholder banner with a
  functional search form and result list. The new `projectQaHistory()`
  Alpine factory wraps the existing `/api/recall` endpoint, populates
  on first activation via `$watch('$root.active', …)`, and renders
  entries as a collapsed list of `(timestamp · tool · question)` with
  the full answer behind a `<details>` toggle.
- **Settings → daily call budget**: replaced the static "inherits" row
  with an editable form. The new `projectSettings()` Alpine factory
  GETs the effective three-axis budget on mount, lets the operator
  type a per-project override (or leave empty to inherit), and PUTs the
  new value back. The footer line shows tightest-cap-wins data inline.
- **`GET /api/projects/{name}/budget`**: returns the effective budget
  triad — `per_host`, `per_tool`, `per_project`, plus
  `tightest_cap_axis` / `tightest_cap_value`. Resolves the per-project
  value from `<project>/.harbormaster.toml` `[budget].daily_call_budget`
  first, falling back to `[hosts.*.projects.<name>]` cells.
- **`PUT /api/projects/{name}/budget`**: writes (or removes) the
  per-project key atomically via temp + rename, preserves other top-level
  tables (e.g. `[markdown]`), rejects zero/negative values, and returns
  the recomputed effective budget so the form re-syncs without a second
  GET.

## What we learned / re-confirmed

- **Single-quote factory mount pattern (v19.a9 lesson) held**. Both new
  factories follow `factory('{{ name | e }}')`, never `tojson` in a
  double-quoted attribute. The new test_v21 suite asserts this directly
  so the pattern can't regress quietly.
- **No tomli-w needed for a 2-line table**. Hand-rolled a 12-line
  `_toml_value` + `_write_project_budget_toml` that handles the
  preserve-other-tables case. Adding a dependency for this would have
  been over-spec.
- **Pre-existing test failure unrelated to this PR**:
  `test_v19_project_tabs::test_trajectories_tab_contains_trajectory_list_component`
  greps for `x-data="trajectoryList({` (double quote) but the template
  uses `x-data='trajectoryList({` (single quote). Confirmed pre-existing
  via `git stash`; left alone — outside this phase's scope.

## Files touched

- `src/harbormaster/ui/templates/project_detail.html` — replaced two
  placeholder/static panels + appended two Alpine factories.
- `src/harbormaster/ui/routes.py` — added `tomllib` + `ConfigDict`
  imports, GET/PUT budget endpoints, plus helpers
  (`_read_project_budget_toml`, `_write_project_budget_toml`,
  `_toml_value`, `_effective_budget_for_project`).
- `tests/ui/test_v21_qa_history_and_settings.py` — new (12 tests:
  template invariants + endpoint behaviour).
- `tests/ui/test_v19_project_tabs.py` — updated two assertions that
  pinned now-superseded v19 behaviour (placeholder removed; settings
  block now form-shaped, not `<dl>`-only).
- `src/harbormaster/__init__.py` — version bump 21.0.0a1 → 21.0.0a2.

## Carry-overs

- The pre-existing `trajectoryList` quote-style test failure is a
  one-character fix (`"` → `'`) but lives outside the v21.a2 scope.
  Worth folding into the next maintenance pass.

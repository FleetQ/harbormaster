# Sprint Retro — Harbormaster v24.0.0a4

**Date:** 2026-05-13
**Theme:** Extract `routes_budgets.py` — the 5 budget endpoints +
their TOML writers. Also extracts the shared `_toml_value` helper to
`harbormaster.ui._toml_helpers` so the accent picker can share it
without a circular import.

## What landed

| File | Subject |
|---|---|
| `src/harbormaster/ui/_toml_helpers.py` | new — `toml_value(v)` hand-written TOML scalar serializer |
| `src/harbormaster/ui/routes_budgets.py` | new — 5 endpoints + helpers + module-level `_ProjectBudgetPutBody` |
| `src/harbormaster/ui/routes.py` | imports `toml_value` at module top; budget block (437 LOC) replaced by import + register call; accent picker uses shared `toml_value` |
| `src/harbormaster/__init__.py` | 24.0.0a3 → 24.0.0a4 |
| `docs/sprint-retro-harbormaster-v24.0.0a4.md` | this file |

## Numbers

- 5 files (3 new, 2 modified).
- `routes.py`: ~2760 (after v23 splits) → ~2320 LOC (-440). Cumulative
  across the v23+v24 split arc: 3064 → ~2320 (-744, **-24%**).
- 2023 → 2023 tests (unchanged). mypy --strict clean on **75 source
  files**. ruff clean.

## Design notes

### `_ProjectBudgetPutBody` must be at module level

FastAPI's body-schema introspection treats nested Pydantic models
differently than module-level ones. When the class lived inside
`register_budget_routes`, every PUT request returned 422 with
`{"loc":["query","body"]}` — FastAPI was reading the body parameter
as a query field because it couldn't resolve the schema.

Moving the class to module level (just below the imports) fixed it.
Test suite caught this immediately. Captured as a comment in the
module so a future contributor doesn't move it back to "tidy up".

### Shared `toml_value` helper

The hand-written TOML serializer was duplicated between
`_write_project_budget_toml` and `_write_accent_toml`. v24.0.0a4
extracts it to `harbormaster.ui._toml_helpers.toml_value`. Both
writers now import from there.

Naming: leading underscore drops because module-level helpers don't
benefit from the protected-by-convention prefix when the function is
genuinely shared. The module name `_toml_helpers` keeps the
"internal-ish" signal (underscore prefix on the file name means "not
part of the public Python API surface").

### `_effective_budget_for_project` lost a dead `pass`

While extracting, removed an `elif name in host_cfg.projects: pass`
branch that was dead code (handled implicitly). Pure cleanup; behaviour
identical. mypy + ruff confirm.

## Carry-over

- v24.0.0a5: dashboard.html template split (conservative)
- v24.0.0a6: project_detail.html template split (conservative)
- v24.0.0a7: FleetQ webhook subscriber
- v24.0.0 GA

After v24.0.0a4, `routes.py` is at ~2320 LOC. Half of that is the
`/mcp/{server}` proxy + dashboard `/` page + projects/{name} +
auth/cookie endpoints — much more cohesive than the kitchen-sink it
was at v22.2.0. The remaining template splits (a5, a6) close out the
big-file debt for v24.

## Operator-facing note

After upgrading to v24.0.0a4:

- **No new endpoints, no removed endpoints, no signature changes.**
  All 5 budget endpoints (`/api/hosts/budget`, `/api/tools/budget`,
  `/api/projects/budget`, `/api/projects/{name}/budget` GET + PUT)
  behave identically.
- The accent picker (`PUT /api/settings/accent`) continues to write
  `[ui] accent_hue/accent_chroma` to the user config TOML — same
  output bytes, just routed through the shared serializer.
- If you're reading source: budget code now lives in
  `routes_budgets.py`. The PUT-body Pydantic model is at module
  level — moving it back inside the register function will break
  FastAPI body resolution (422 on every PUT).

# Sprint Retro — Harbormaster v15.0.0a4

**Date:** 2026-05-10
**Theme:** N-way reembed comparison + per-tool budget.

## What shipped

- **N-way reembed run comparison** (v14 candidate #8): generalises the
  v13.0.0a3 2-way diff. New endpoint
  `GET /api/history/reembed/runs/compare?indices=0,2,5` returns
  side-by-side per-field values for up to 4 runs (UI cap — beyond
  that the table becomes unreadable). Indices are zero-based offsets
  into the chronological list; duplicates stripped, order preserved.
  Per-field projections: `duration_seconds`, `total`, `succeeded`,
  `failed`, `cancelled`, `model`. 400 on >4 / non-integer / empty;
  404 on out-of-range.
- **Per-tool budget** (v14 candidate #9): new `BudgetConfig` Pydantic
  section bound to `[budget]` in TOML. Single field
  `daily_call_budget_per_tool: dict[str, int]` (validated > 0). New
  endpoint `GET /api/tools/budget` mirrors `/api/hosts/budget` shape;
  unbudgeted-but-called tools appear with `budget: null`.
  Dashboard host-budget KPI cell now expands on hover to show the
  per-tool breakdown — lazily fetched on first hover, polled on the
  same 30s tick afterwards.
- **Doc parity**: added `[budget]` section to
  `docs/operator-config-reference.md` (closes the v13.0.0a3 doc-parity
  check that fired on the new field).

## Numbers

- **Tests**: 1468 → 1486 (+18)
- **Source files**: 57 (no change — extension to `config.py` +
  `network_store.py` + `routes.py` + template)
- **Wall-clock**: ~30 min
- **Commits on main**: 1 feature merge
- **Lint / type**: ruff clean (5 SIM117 nested-with manually combined
  via the `with patch(...), TestClient(app) as client:` pattern from
  v15.a2), `mypy --strict` clean
- **Backwards-incompatible changes**: 0

## What worked

- **Mirror, don't invent.** `BudgetConfig` is a structural twin of
  `HostConfig.daily_call_budget`; `/api/tools/budget` is a structural
  twin of `/api/hosts/budget`. Tests, docs, and template wiring all
  followed by analogy.
- **Lazy-loaded hover.** Operators that never hover the host-budget
  KPI cell never trigger the per-tool fetch. Once loaded, the 30s
  polling tick keeps it fresh — but only if it's been loaded once.
- **Auto-use isolation fixture.** v14 had this pattern in one test
  file; promoted to v15.a4's whole module. Caught a real failure
  (the `test_api_tools_budget_returns_empty` assertion fired only
  under the full suite where another test had recorded events into
  the shared singleton).

## What to change

- **Doc-parity test fires loud, no auto-suggest.** v13.0.0a3's parity
  check told me `BudgetConfig.daily_call_budget_per_tool` was
  undocumented, but didn't suggest the right doc section to add.
  Was easy here (one new section), but the v15.a5 pre-commit hook
  candidate could include a "suggested edit" output mode.
- **Two-step Edit fix for SIM117.** `--unsafe-fixes` didn't auto-apply
  the combined-with rewrite for my pattern; had to combine the 5
  spots by hand. The pattern is repeatable enough to bake into the
  test template if we add a v16 candidate.

## Next phase (v15.0.0a5)

- Pre-commit hook integration (v14 candidates #10, #11)
- DOES NOT touch `.github/workflows/*` — pre-commit lives in
  `.pre-commit-config.yaml` at repo root, fine without `workflow`
  scope.

## Halt assessment

- 5 v14 candidates remain; v15.0.0a4 closes 2 more (9 total of 12).
- Test suite green, lint clean, no breaking changes — release bar met.
- **Continue.**

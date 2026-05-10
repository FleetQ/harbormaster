# Sprint Retro — Harbormaster v15.0.0a6

**Date:** 2026-05-10
**Theme:** Carry-over polish bundle — per-project markdown config +
dashboard tour wizard.

## What shipped

- **Per-project markdown render config**: new `MarkdownConfig`
  Pydantic section bound to `[markdown]` in TOML. Single field
  `strict: bool = True` (matches v11.0.0a3 byte-for-byte). When
  `strict = false`, the bleach allowlist widens to also accept
  `<span>`, `<kbd>`, `<mark>`, `<figure>`, `<figcaption>` AND
  `markdown-it` switches to its `html=True` parser so raw inline
  HTML survives to bleach for whitelist filtering. Per-project
  override: drop `[markdown] strict = false` in
  `<project_path>/.harbormaster.toml`. `/api/render-markdown` gains
  an optional `project` field on the request body; the per-project
  value wins over the global one. Unknown project name silently
  falls through to the global value (operator-side feature, never
  block rendering).
- **Dashboard tour wizard**: 5-step interactive walkthrough on first
  dashboard load, gated by `localStorage['hm-tour-completed']`.
  Steps anchor to existing selectors via `querySelector` — no
  markup changes to anchors. Anchors: KPI strip (projects cell),
  sidebar (`#hm-sidebar`), ask form (`section[x-data^="askForm"]`),
  command palette, memories panel. Re-trigger via `?tour=1` query
  string. Skip ≠ complete (operator can come back).
- **Doc + example updated** to include the new `[markdown]` section.

## Numbers

- **Tests**: 1498 → 1521 (+23)
- **Source files**: 57 (no change — extensions only)
- **Wall-clock**: ~30 min
- **Commits on main**: 1 feature merge
- **Lint / type**: ruff clean, `mypy --strict` clean
- **Backwards-incompatible changes**: 0 (`render_safe(text)` without
  the new kwarg defaults to strict; all v11..v14 callers see byte-
  identical output).

## What worked

- **Two markdown-it instances, not one toggled.** Keeping a
  `_md` (`html=False`, default) and `_md_html` (`html=True`, opt-in)
  module-level instance avoids per-call init cost and makes the
  contract obvious from the function body. Bleach is the second
  rail either way.
- **Tour anchored via querySelector, not data-attrs.** Means we
  did NOT have to add `data-tour-step` attributes throughout the
  template — selectors target existing constructs. The tradeoff:
  if those selectors change, the tour breaks silently. Acceptable
  for v15 (the selectors target stable v8.0.0a6 patterns).
- **PYTHONPATH injection in CLI test.** v15.a5's
  `test_config_check_cli_passes_against_example` was failing here
  because the venv-installed harbormaster snapshot didn't have the
  new `[markdown]` section. One-line fix: prepend the worktree's
  `src/` to `PYTHONPATH` in the env passed to `subprocess.run`.

## What to change

- **Tour step selector fragility.** Mentioned above — selectors
  could break under template refactors with no test coverage. v16
  candidate: bake `data-tour-step="N"` into the anchors with a
  lookup helper, so refactors flag the breakage at build time.
- **Two markdown-it instances duplicate enable() boilerplate.** A
  `_make_parser(html: bool)` helper would dedupe the init. Trivial,
  not worth a v15 patch — flag for v16 if the parser config grows.

## Halt assessment

- **All v15 alphas (a1-a6) shipped on plan.** 11 of 12 v14 candidates
  closed; #1 (re-land CI workflow) remains operator-action.
- Test suite green, lint clean, no breaking changes — release bar met.
- **Continue to v15.0.0 GA.**

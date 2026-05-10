# Sprint Retro — Harbormaster v15.0.0a5

**Date:** 2026-05-10
**Theme:** Pre-commit hook integration — both v14 candidates that
share the pre-commit theme.

## What shipped

- **`harbormaster-mcp config check` as pre-commit hook** (v14 #10):
  new `.pre-commit-config.yaml` with a local hook that runs the
  validation CLI against `examples/harbormaster.toml` on every
  commit. Triggered only when the example or `config.py` change.
- **Auto-fail pre-commit when a config field lacks doc** (v14 #11):
  new `scripts/check_config_doc_parity.py` walks every Pydantic
  field on `HarbormasterConfig` (and its nested sub-models) and
  fails (rc=1) if any field name is missing from
  `docs/operator-config-reference.md`. Same coverage rule as the
  v13.0.0a6 pytest test, extracted as a stand-alone script so the
  hook doesn't need pytest in scope.
- **`examples/harbormaster.toml`**: brand-new annotated example that
  exercises every shipped TOML section (the parity hook + the
  config-check hook both target it).
- **README**: new "Pre-commit hooks" section with install + opt-in
  steps for operators.

## SAFETY

- **Zero changes to `.github/workflows/*`.** Both hooks live entirely
  at repo root + `scripts/`. The `.pre-commit-config.yaml` file's
  only mention of `.github/workflows` is a comment explicitly
  stating the rail; a test (`test_precommit_does_not_touch_github_workflows`)
  asserts no actual hook config references it (strips comments first).

## Numbers

- **Tests**: 1486 → 1498 (+12)
- **Source files**: 57 (no change — new files live in
  `examples/` + `scripts/` + repo root, not `src/harbormaster/`)
- **Wall-clock**: ~30 min
- **Commits on main**: 1 feature merge
- **Lint / type**: ruff clean, `mypy --strict` clean
- **Backwards-incompatible changes**: 0

## What worked

- **Reuse the v13 doc-parity test logic.** The pytest test already
  walks the Pydantic model tree; lifted that walk into
  `find_undocumented(doc_path)` for the script. The pytest test
  stays as the in-suite gate; the script is the per-commit gate.
- **Annotated example `examples/harbormaster.toml`.** Doubles as
  documentation (sections show defaults inline) and the hook target.
  Operators can `cp examples/harbormaster.toml ~/.config/harbormaster/config.toml`
  as a starting point.
- **Module-entry-point invocation in tests.** `python -m harbormaster
  config check` works whether or not `harbormaster-mcp` is on PATH —
  more robust than `shutil.which` lookup.

## What to change

- **Pre-commit isn't a dev dep.** The hook config is shipped, but
  installing pre-commit itself is on the operator (via pipx or pip).
  v15.a6 candidate already covers per-project markdown config; a
  future candidate could optionally add pre-commit as an extras
  bundle (`pip install harbormaster-mcp[dev]`).
- **Comment-vs-content discrimination.** Initial test failure was
  "the YAML comment mentions `.github/workflows`." Comment-stripping
  fix is a one-liner but flagged a pattern: when SAFETY rails get
  documented in a YAML comment, regression tests must strip comments.

## Next phase (v15.0.0a6)

- Per-project markdown render config (`<project>/.harbormaster.toml`
  with `[markdown] strict = true|false`)
- Dashboard tour wizard (5-step popover walkthrough)

## Halt assessment

- 3 v14 candidates remain (the deferred CI workflow #1 + the two
  long-standing carry-overs); v15.0.0a5 closes 2 more (11 total of 12).
- Test suite green, lint clean, no breaking changes — release bar met.
- **Continue.**

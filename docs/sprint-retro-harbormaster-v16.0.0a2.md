# Sprint Retro — Harbormaster v16.0.0a2

**Date:** 2026-05-10
**Theme:** Pre-commit polish — three carry-overs that combine cleanly
because they all sit around the v15.0.0a5 hook surface.

## What shipped

- **`pre-commit>=3` in the `[dev]` extra** (carry-over #4). One
  line in `pyproject.toml` so `uv sync --extra dev` is the single
  bootstrap command for new contributors. The system / pipx fallback
  still works.
- **`scripts/post_sync_install_hooks.sh`** (carry-over #12). One
  shell script that wires `.git/hooks/pre-commit` after the first
  sync. Picks `.venv/bin/pre-commit` first, falls through to a
  system / pipx pre-commit on PATH. Idempotent; safe to re-run.
- **Suggested-edit output from doc-parity script** (carry-over #5).
  When `scripts/check_config_doc_parity.py` finds a missing field,
  it now emits a copy-paste-ready markdown stanza on stderr,
  delimited by `# ---` markers. Each entry includes the model name,
  field name (backticked), Python type, and default — operator
  pastes verbatim under the right `[section]` heading.
- **README updated** with the new install flow and a one-paragraph
  description of the suggested-edit output.

## Numbers

- **Tests**: 1535 → 1544 (+9 net new)
- **Source files**: 57 (unchanged — extensions only; the new shell
  script lives in `scripts/`, the doc-parity changes are in the
  same standalone script)
- **Wall-clock**: ~20 min
- **Commits on main**: 1 feature merge
- **Lint / type**: ruff clean, `mypy --strict` clean
- **Backwards-incompatible changes**: 0
  - `find_undocumented()`'s return shape changed from `list[str]`
    to `list[tuple[...]]` — but the function is only called from
    `main()` in the same file (no external caller).
- **Confirmation: did NOT touch `.github/workflows/*`** — yes.

## What worked

- **Group by model in suggested edit.** When 5 fields land in a new
  `BudgetConfig` model, the output becomes one `### BudgetConfig`
  block — operator drops it under the `[budget]` heading and the
  parity hook goes green on the next commit. No per-field hunt.
- **Shell script over uv post-sync hook.** `uv` doesn't expose a
  post-sync hook as of 0.4 / 0.5; the operator-runs-once shell
  script is the smallest contract that gets the job done. Avoids
  betting on a future uv API that might not arrive.
- **CWD discipline held.** All Bash calls in this phase ran from
  the worktree CWD without explicit `cd`. Discipline lapses for
  v16.a2: **0**.

## What to change for the next phase

- Continue with carry-overs #6 (`data-tour-step` markup) + #8
  (network-page tour anchors) for v16.a3 — both are tour-related
  and combine cleanly. Expect to lean on the v15.a6 tour wiring.

## Notes for v16.a6 split decision

Backend instrumentation (the risky part) hasn't started yet.
Decision deferred to a6 itself.

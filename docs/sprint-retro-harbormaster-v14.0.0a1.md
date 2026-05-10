# Sprint Retro — Harbormaster v14.0.0a1

**Date:** 2026-05-10
**Theme:** Close v13.a1 op-step (manual screenshot bless) and verify the v12.a5 wt-merge helper.

## What landed

### `harbormaster` (this repo)

| SHA | Subject |
|-----|---------|
| `90da2ae` | feat(v14.0.0a1): screenshot autobootstrap + wt-merge --dry-run |

## Capabilities (this sprint)

### 1 · Screenshot baselines auto-bless on main-push

Added `HM_SCREENSHOT_AUTOBOOTSTRAP=1` env var to the
`tests/ui/_screenshot_diff/` harness. When set AND a baseline PNG is
missing, the harness writes the captured screenshot directly to the
canonical baseline path (instead of `__actual.png`) and the test
passes. The CI `smoke-ui-browser` job sets this env var on
`push -> main` events only — pull-request runs continue to assert
against the committed baselines (or skip with the bootstrap message
if missing). After the test pass, the CI job stages baseline PNGs
by explicit pathspec (never `git add -A`, never `*__actual.png` or
`*__diff.png`) and pushes a `ci: auto-bless screenshot baselines`
commit back to `main` via `github-actions[bot]`.

The function is distinct from the existing `is_bootstrap_mode()`
(which only writes `__actual.png` for human review and skips the
test) — keeping both behaviours lets local operators continue using
the manual flow while CI does the automated one.

### 2 · `scripts/wt-merge.sh --dry-run`

Added `--dry-run` / `-n` flag to the worktree-to-main merge helper.
All invariants are still checked (clean tree, not on main, parent
detect via `git worktree list --porcelain`), but the actual `git
push` and parent `git merge --no-ff` are skipped. Lets operators
sanity-check the parent-detect logic before committing to the
side-effecting flow.

The v13.a1 retro reported a `PARENT…` truncation in the script —
investigation showed `bash -n scripts/wt-merge.sh` is clean and the
report was a UTF-8 ellipsis transcription artefact, not a real
corruption. No structural fix needed.

## Real numbers

- 1/1 sprint-plan items shipped (auto-bless + dry-run combined)
- 1 commit (single PR-equivalent)
- 3 new unit tests in `tests/ui/_screenshot_diff/test_helper_unit.py`:
  `test_bootstrap_mode_env_gating`, `test_autobootstrap_writes_baseline_in_place`,
  and the original `test_baseline_path_helper` re-verified
- Test suite delta: 1359 → 1361 passed (+2 net; one collected test
  delta from a `test_screenshots.py` skip path)
- Lint: ruff clean. Type-check: `mypy --strict` clean (56 source files).
- Backwards-incompatible changes: 0. New env var defaults to off.

## What worked

- **Verifying the helper before assuming it was broken.** The v13
  retro flagged the wt-merge script as suspect; running `bash -n`
  + executing `--help` immediately ruled out a real corruption.
  Spending 30 seconds to verify before fixing avoided wasted work.
- **Symmetry with the existing `is_bootstrap_mode()` API.** The
  new `is_autobootstrap_mode()` mirrors the existing helper exactly
  (env var name + `"1"` literal check), keeping conftest.py
  scannable and giving the test logic a clean if-elif ladder.
- **CI push-back stages by explicit pathspec.** The new commit-back
  step uses a `for f in baseline/*.png; do case … esac; done`
  loop instead of `git add -A`, so a stray `__actual.png` from a
  failing test can never end up in the baseline commit.

## What to change / next

- **Push-back from CI needs a one-time manual approval on first
  run.** The first `main`-push that triggers the new workflow will
  use `secrets.GITHUB_TOKEN` with `contents: write` — repo settings
  may need "Read and write permissions" enabled under Actions
  settings. Document this in the v14.0.0 GA retro.
- **OAuth scope blocks workflow pushes locally.** `wt-merge.sh`
  push step failed with "OAuth App without `workflow` scope" when
  the branch contained `.github/workflows/ci.yml` changes. Worked
  around by merging into local parent without the remote backup
  push (CI workflow ships when main is later pushed). Consider
  documenting this in `wt-merge.sh` usage as a known case.

## Action items for the next sprint (v14.0.0a2)

1. **`harbormaster-mcp config check` CLI subcommand.** New CLI
   subcommand that loads config and prints a validation report.
   Exit 0 / 1 / 2 depending on warning / error severity. Useful
   as a CI gate or pre-flight check for operators.
2. **Auto-derive network-filter source dropdown.** v13.a4 currently
   hardcodes the dropdown options; derive them from distinct
   `source` values in the last 1000 events instead.

## Out-of-scope (still)

- Pixel-diff golden updates with structural-similarity (SSIM) instead
  of bbox histogram — current 0.5% tolerance has been stable for one
  sprint, no real-world false positives yet.
- A self-service `wt-merge.sh undo` to roll back a botched merge —
  the merge is `--no-ff`, so a single `git reset --hard HEAD~1` on
  the parent is enough; not worth scripting yet.

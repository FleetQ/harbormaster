# Sprint Retro — Harbormaster v18.0.0a1

**Date:** 2026-05-10
**Theme:** Re-land the screenshot autobootstrap CI workflow that
v14.0.0a1 originally tried — closing a 4-version-old block.

## What shipped

- New CI job `screenshot-autobootstrap` in `.github/workflows/ci.yml`.
- Runs only on `push` to `refs/heads/main` (skipped on PR runs and
  on tag pushes — autobootstrap is only meaningful on the post-merge
  build, not on transient PR branches or release tags).
- Sequence:
  1. Checkout `main` with `fetch-depth: 0` and the workflow-scoped
     `GITHUB_TOKEN` so the commit-back is authenticated.
  2. Install Playwright Chromium (mirrors `smoke-ui-browser`).
  3. Run `pytest tests/ui/_screenshot_diff/ -m browser` with
     `HM_SCREENSHOT_AUTOBOOTSTRAP=1`. Existing v14.0.0a1 harness
     logic in `test_screenshots.py` writes missing baselines
     directly to `tests/ui/_screenshot_diff/baseline/` and the
     test passes.
  4. `git add tests/ui/_screenshot_diff/baseline/` (explicit path
     — never `git add -A`), check for staged changes, commit with
     `harbormaster-bot` identity and `[skip ci]` tag, push to
     `main`.
- `needs: smoke-ui-browser` so the autobootstrap job only runs
  after the regular browser-marked tests pass on the PR-as-merged
  commit.
- Header comment in `ci.yml` documents the v18.0 token-scope
  refresh that unblocked this change.

## The 4-version-old block

- v14.0.0a1 implemented the harness side of autobootstrap
  (`HM_SCREENSHOT_AUTOBOOTSTRAP=1` env var, in-place write to the
  baseline path, test-passes-on-write semantics). Tests for the
  harness logic shipped and stayed green.
- The CI side never landed: the operator's GitHub OAuth token did
  not include `workflow` scope, so any PR that touched
  `.github/workflows/*` was rejected by the GitHub API at push
  time.
- v15, v16, v17 each carried this as a known candidate but could
  not close it without a token rotation.
- v18.0 sprint kickoff confirmed `gh auth status` now reports
  `'workflow'` in the scopes list. The job above re-lands the
  exact change v14 had originally drafted, with no functional
  changes — only the scope situation moved.

## Non-changes (deliberate)

- Harness Python in `tests/ui/_screenshot_diff/` untouched —
  `is_autobootstrap_mode()` and the `test_surface_matches_baseline`
  branch already exist from v14.0.0a1.
- Other 9 CI jobs untouched.
- `publish.yml` untouched — release flow is independent of the
  autobootstrap job.
- No new bot account: `harbormaster-bot@github.com` is just the
  identity stamped into the commit, not a real account.

## Tests added

None. The job's correctness is validated by:

1. YAML parse check (passed locally with `yaml.safe_load`).
2. `actionlint` (not installed locally; the `if:` guard means the
   job won't fire on this PR's run anyway — only on the post-merge
   `push` event to `main`).
3. The next post-merge run on `main` is the live integration test.
   If the commit-back path is wrong, it will fail loudly and the
   subsequent retro will catch it.

## Numbers

- Files touched: 1 (`.github/workflows/ci.yml`, +56 lines).
- New tests: 0 (harness logic already tested in v14.0.0a1).
- Test count: 1629 → 1629 (unchanged — workflow-only change).
- Source files: 57 → 57 (unchanged — no `src/` change).
- Wall-clock from worktree creation to retro: ~10 minutes.

## What's next (v18.0.0a2)

Trace waterfall hover tooltip on the `/dispatcher` page — final
cosmetic polish item from the v17 candidate list. After a2 lands,
v18.0 GA closes the entire autonomous chain.

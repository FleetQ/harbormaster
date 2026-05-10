# Sprint Retro — Harbormaster v12.0.0a5

**Theme:** Network stats by-source breakdown + worktree helper script.
Two small items combined.

## What shipped

### `/api/network/stats` extension

`NetworkStore.stats()` now returns an additional field:

```json
{
  "total_calls": ...,
  "by_tool": {...},
  "by_source": {
    "operator":  {"calls": 80, "error_rate": 0.01},
    "alpha":     {"calls": 30, "error_rate": 0.0},
    "beta":      {"calls": 12, "error_rate": 0.083}
  },
  "top_projects_by_calls": [...],
  "error_rate": ...
}
```

- `by_source` keys are caller names — `operator` for direct dashboard
  / API use, project names for the cross-project routing wired in
  v11.0.0a1 via the `X-Caller-Project` header.
- `error_rate` per source (errors / total) is a per-caller affordance:
  a misbehaving project shows up with a high rate even if its absolute
  call count is small.
- `since_ms` window filter applies the same way as the existing
  total / by_tool aggregates.
- All previous fields preserved — pure additive change.

### Network stats panel UI (`templates/network.html`)

- Grid grows from `md:grid-cols-4` to `md:grid-cols-5`. New "by source"
  cell renders one line per source with call count + a per-source
  error-rate badge that's only shown when the rate is non-zero (keeps
  the panel quiet in the happy path).
- `<template x-for="(row, source) in stats?.by_source ?? {}">`.
- Per-source error badge: amber, formatted as `(N% err)`.

### Worktree helper script (`scripts/wt-merge.sh`)

Codifies the two-step merge flow learned during v11. Pulls the
common pattern out of the per-phase prompt:

  1. Push the worktree branch to origin (backup).
  2. Detect the parent (main) checkout via `git worktree list --porcelain`.
  3. `git merge --no-ff <branch>` in the parent — preserves phase
     boundary in `git log --oneline`.

Invariants enforced (test-pinned):

- Refuses to run from `main` / `master`.
- Working tree must be clean (no uncommitted changes).
- Parent path auto-detected; works for any worktree name, not just
  one hard-coded path.
- `REMOTE` env override for fork-based workflows (`REMOTE=upstream
  bash scripts/wt-merge.sh`).
- Never force-pushes. Never amends.
- `set -euo pipefail` guards against silent failures in the chain.

Usage:

```
bash scripts/wt-merge.sh                   # current branch
bash scripts/wt-merge.sh feat/v12.0-foo    # explicit
bash scripts/wt-merge.sh --help
```

## Tests

| Suite delta                                       | Before | After |
|---------------------------------------------------|-------:|------:|
| Total tests                                       | 1269   | 1281  |
| New (`tests/ui/test_network_stats_by_source.py`)  | —      |   +12 |

Coverage:

- `stats()` returns `by_source` field shape (dict with `calls` +
  `error_rate`).
- Per-caller call counts + error rates computed correctly with
  three callers and one error.
- `since_ms` window filter trims old rows from `by_source`.
- Empty DB → `by_source == {}`.
- API endpoint surfaces the field in JSON.
- UI renders `by_source` in the stats panel + per-source error
  badge.
- Helper script: file exists + executable bit set.
- `--help` flag prints usage and exits 0.
- Header documents the contract (clean tree, refuses main, parent
  detection, --no-ff, never force-push).
- `REMOTE` env override pattern present.
- Merge format `Merge $BRANCH` matches autonomous-sprint convention.
- `set -euo pipefail` present.

## Quality gates

```
mypy --strict src/harbormaster   →  Success: no issues found in 56 source files
ruff check src tests              →  All checks passed!
pytest -q                         →  1281 passed, 2 skipped in 39.61s
```

## Architecture notes

- **Why two items in one phase?** Both touch operator-facing
  observability / workflow plumbing and neither warrants its own
  retro. v11's plan-then-bundle-related-items pattern (recorded in
  v5's session retro) applied.
- **Why expose `error_rate` per source rather than a count?** Two
  reasons. (1) It composes — easy to multiply by `calls` to recover
  the count if needed. (2) It surfaces the operationally meaningful
  number directly: a 50% error rate on 4 calls is more interesting
  than 2 raw errors among 100 successful calls elsewhere.
- **Why hide the per-source error badge when zero?** The panel is
  scanned visually. A column of "(0% err)" labels is noise; their
  absence is the signal "everything is fine for this source".
- **Why a shell helper instead of a Python CLI?** The helper runs
  BEFORE the venv is necessarily active (e.g. fresh clone, before
  `uv sync`). Bash + `git` is the lowest-common-denominator surface.
  The script also has zero dependencies — testable purely via
  `subprocess.run`.
- **Why auto-detect the parent path?** The original v11 prompt
  hard-coded `~/htdocs/harbormaster`. That breaks for any other
  operator. `git worktree list --porcelain` is the right primitive
  — it's stable, machine-readable, and works for any layout.

## Deviations

None. Phase scope matched plan exactly.

## Next

Phase 6 — cookie-backed bearer for SSE auth.

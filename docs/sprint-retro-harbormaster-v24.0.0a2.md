# Sprint Retro — Harbormaster v24.0.0a2

**Date:** 2026-05-13
**Theme:** `auto_commit` parameter on `delegate_task`. Operator can
now authorise the subagent to commit its own changes after edits —
closes the "subagent edits + operator commits manually" friction
point for trusted delegations.

## What landed

| File | Subject |
|---|---|
| `src/harbormaster/jobs/schema.py` | `MIGRATIONS` += `auto_commit INTEGER NOT NULL DEFAULT 0` |
| `src/harbormaster/jobs/store.py` | `Job.auto_commit: bool`; `enqueue()` accepts `auto_commit=`; `as_dict()` includes it; `_row_to_job` reads it |
| `src/harbormaster/jobs/worker.py` | `build_async_delegate_prompt` branches: read-only / writes / writes-auto-commit |
| `src/harbormaster/tools/delegate.py` | New `auto_commit: bool = False` param on `delegate_task`; sync + async paths honour it; `_WRITES_AUTO_COMMIT_SUFFIX` new constant |
| `tests/unit/test_auto_commit.py` | 6 new tests (sync default, sync auto, no-escalate, persistence, worker prompt, legacy DB migration) |
| `src/harbormaster/__init__.py` | 24.0.0a1 → 24.0.0a2 |

## Numbers

- 6 files (2 new, 4 modified). ~80 net LOC.
- 2017 → 2023 tests (+6). mypy --strict clean. ruff clean.

## Design notes

### Prompt-branch is the gate

Same shape as v22.0.0a1's allow_writes lift — the change isn't in
subprocess flags (`--permission-mode bypassPermissions` stays on
either way), it's in the prompt suffix. Three suffixes now:

| allow_writes | auto_commit | Suffix |
|:---:|:---:|---|
| False | * | `_READ_ONLY_SUFFIX` |
| True | False | `_WRITES_SUFFIX` (operator commits) |
| True | True | `_WRITES_AUTO_COMMIT_SUFFIX` (subagent commits) |

`auto_commit=True` without `allow_writes=True` is a no-op — privilege
does not escalate via just the commit flag. Regression-guarded by
`test_sync_delegate_auto_commit_without_allow_writes_stays_read_only`.

### Subagent commits, never pushes

`_WRITES_AUTO_COMMIT_SUFFIX` explicitly says "Do NOT push — the
operator pushes after review." Pushing is a shared-state action with
remote-repo blast radius (per global CLAUDE.md "Action Safety"); the
operator stays in the loop for that one step. The subagent's commits
sit on a feature branch ready for `git push` when the operator OKs
the changes.

### Schema migration mirrors v22.0.1's max_turns pattern

`MIGRATIONS` list extended with one more tuple
`("auto_commit", "auto_commit INTEGER NOT NULL DEFAULT 0")`. The
`_apply_migrations` runner from v22.0.1 picks it up automatically
on next JobStore open. Existing rows backfill to 0 (=False) — same
shape as max_turns backfill behaviour.

## Lessons

### "Soft assertions" in tests need to be substring-aware

First test for read-only-when-auto_commit-but-no-allow_writes asserted
`"edit files" not in prompt` — false positive because the read-only
suffix says `"Do NOT edit files."` (which contains "edit files" as a
substring). Fixed by asserting the writes-only intro
`"You may edit files"` instead.

Pattern: when negating a prompt-content assertion, pick a string
that's specific to ONE prompt branch. Generic phrases (`"edit files"`)
sneak in via negations in other branches.

## Carry-over

- v24.0.0a3: max_turns UI hints on /jobs page
- v24.0.0a4: extract routes_budgets.py
- v24.0.0a5: dashboard.html template split (conservative)
- v24.0.0a6: project_detail.html template split (conservative)
- v24.0.0a7: FleetQ Bridge completion-webhook subscriber (Tier 3
  close-out — FleetQ side delivered the endpoint)
- v24.0.0 GA: arc retro + memory refresh

## Operator-facing note

After upgrading to v24.0.0a2:

- Existing `delegate_task` callers unchanged — `auto_commit` defaults
  to `False`, matches v22+ "subagent edits, operator commits" workflow.
- To delegate the commit step:
  ```python
  delegate_task(
      name="...", task="...", deliverable="...",
      allow_writes=True, auto_commit=True, mode="async",
      max_turns=80,   # higher because commit + test cycles take turns
  )
  ```
- `allow_writes=True + auto_commit=True` means the subagent will
  write, test, and commit. Pushing remains operator-controlled.
- `auto_commit=True` alone (without `allow_writes`) is a no-op —
  by design, to prevent accidental privilege escalation via a flag
  flip.
- New schema column auto-migrated on next JobStore open. Existing
  rows backfill to `auto_commit=False`.

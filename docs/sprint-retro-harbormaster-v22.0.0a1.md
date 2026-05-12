# Sprint Retro — Harbormaster v22.0.0a1

**Date:** 2026-05-12
**Theme:** Lifted the v1 write-block on `delegate_task`. The caller
(agent A) now authorises edits via the existing `allow_writes`
parameter instead of receiving a hardcoded "fails closed" error; the
prompt builder branches on the flag. Sync-mode only — async + inbox
arrive in v22.0.0a2.

## What landed

### `harbormaster` (this repo)

| SHA | Subject |
|-----|---------|
| `<short>` | feat: lift v1 write-block; allow_writes=True branches prompt instead of erroring |

## Capabilities (this sprint)

- `delegate_task(..., allow_writes=True)` no longer returns the v1-era
  "Error: ... disabled in v1" string. The tool builds a writes-allowed
  prompt suffix (subagent edits files directly; returns a markdown
  summary of files changed + new tests + follow-ups; does NOT git
  commit) and routes through `run_backend` like the read-only path.
- The HTTP/SSE path in `ui/routes.py::_delegate_task_prompt` mirrors
  the same branch — no more 400 error on `allow_writes=true`.
- A2A agent card text updated: the `delegate-<project>` skill is no
  longer tagged `"read"`-only; description now mentions both modes.
- Default behaviour (`allow_writes=False`) is unchanged — every
  existing caller keeps the same read-only contract.

## What did NOT land (planned for v22.0.0a2+)

- No async mode yet. Calls still block until the subagent returns.
- No JobStore / `delegated_jobs` table.
- No `recall_pending_results` inbox tool.
- No `/jobs` UI surface.
- No agent-A → agent-B inbox identity model.

These are the planned slices for v22.0.0a2 (async + job store + status
tool), v22.0.0a3 (inbox tool), v22.0.0a4 (UI surface), then GA.

## Numbers

- 4 files changed (delegate.py, routes.py, README.md,
  architecture-harbormaster.md), 1 version bump
  (`__init__.py: 21.0.9 → 22.0.0a1`)
- 4 unit tests added (2 in `test_tools.py`, 2 in `test_ui.py`),
  2 removed (the v1 fails-closed assertions). Net +2 tests.
- 1937 passed + 1 skipped on the full suite. mypy --strict clean.
  ruff clean (1 import-sort autofix applied).

## Lessons

### Hardcoded error strings outlive their version

The `"disabled in v1"` message and the `"v1 fails closed"` docstring
sat in `delegate.py` from v1.0.0 all the way through v21.0.9. They
were correct at write time and never re-examined. Downstream agents
pattern-matched on them and propagated the constraint into their own
playbooks ("I'll delegate with allow_writes=False, ask for a diff,
then I'll apply it"), making the original v1 product decision feel
like an immutable architectural property rather than a placeholder
waiting for the v2 approval gate.

**Rule:** when a docstring says "v1 ... v2 will add X", file an issue
or follow-up task at write time. Otherwise the comment becomes the
ceiling.

### `bypassPermissions` was already on; the gate was just the prompt

The investigation turned up that `claude -p --permission-mode
bypassPermissions` was passed unconditionally for both `ask_project`
and `delegate_task` (see `backends/claude.py:137`). The "v1 fails
closed" gate was a prompt-string guard plus a tool-layer early return
— not a permissions barrier. Lifting it was a pure prompt-builder
change; no subprocess flag flipped.

This is good news for v22 — the writes path needs zero subprocess
changes — but it also explains why agents that copy-pasted the gate
behaviour got nervous: the early-return error message *sounded* like
a hard safety boundary when it was really a UX nudge.

### Two paths, one gate

The gate lived in two parallel places:

- `tools/delegate.py` — the MCP tool path (stdio + JSON HTTP)
- `ui/routes.py::_delegate_task_prompt` — the SSE-streaming HTTP path

Both raised the same error. Both got updated in this sprint. If a
future contributor adds a third entry point (e.g., a new transport),
they need to remember the prompt-builder branch. The two prompt
builders are now structurally identical (read-only suffix vs writes
suffix; the writes suffix is the same 73-word block in both places).

**Follow-up for v22.0.0a2:** extract the two suffixes into a shared
constant (`harbormaster.tools._helpers`?) so there's one source of
truth. Deferred to a2 because doing it here would expand the diff
beyond the lift itself.

## Carry-over to v22.0.0a2

1. Add `mode="sync"|"async"` parameter to `delegate_task`. Async path
   returns `{job_id, status: "queued"}` immediately.
2. New SQLite table `delegated_jobs` (id, project, host, task,
   deliverable, allow_writes, status, output, started_at,
   completed_at, duration_ms, cid).
3. `asyncio.create_task` worker that picks up queued jobs.
4. New MCP tool `get_delegated_task(job_id)` for status polling.
5. Restart-recovery: on startup, mark `status=running` rows as
   `status=failed, error="server_restart"`.
6. Extract the prompt suffixes into a shared module (see "Two paths,
   one gate" lesson above).

## Carry-over to v22.0.0a3

- Inbox identity model. Caller-supplied `inbox_id` string + new
  `recall_pending_results(inbox_id, mark_read=True)` tool. Agent A
  polls inbox; harbormaster writes completed/failed jobs there;
  marking-read clears the inbox for the agent.

## Carry-over to v22.0.0a4

- `/jobs` UI page listing `delegated_jobs` with status filter +
  lazy-fetch full output (v21.0.8 pattern). Dashboard counter
  ("N running / M completed today"). Async-wrap any sync FS work
  per v21.0.3.

## Operator-facing note

After upgrading to v22.0.0a1, agents that previously got the
`"Error: ... disabled in v1"` string back from `delegate_task` will
now get a real run with edits applied. Audit your downstream callers
— anyone passing `allow_writes=True` was previously getting the
error string AS THE ANSWER (and silently treating that as a no-op);
they will now get actual changes. Default behaviour
(`allow_writes=False`) is unchanged.

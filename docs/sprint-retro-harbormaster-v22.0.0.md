# Sprint Retro — Harbormaster v22.0.0 (GA)

**Date:** 2026-05-12
**Theme:** Async delegation. Agent A can now hand a task to agent B
in another project, fire-and-forget, and pick up the result later
through an inbox. The v1-era "fails closed on writes" placeholder is
gone — agent A's `allow_writes=True` is honoured. Same surface for
sync (blocking) calls so every existing caller works unchanged.

This GA closes the arc that started 20 versions ago: the original
`delegate.py` docstring promised "v2 adds an explicit approval gate"
in v1.0.0. v22.0.0 ships the alternative: the gate moves from
harbormaster to agent A, where the authorisation actually belongs.

## What landed across the v22.0.0 arc

### `harbormaster` (this repo)

| Tag | Lines | Subject |
|---|---:|---|
| v22.0.0a1 | +266 / -64 | Lift v1 write-block; `allow_writes=True` branches prompt instead of erroring |
| v22.0.0a2 | +1102 / -19 | Async delegate path + JobStore + worker + `get_delegated_task` MCP tool |
| v22.0.0a3 | +304 / -1 | `recall_pending_results` inbox tool with FIFO drain + non-destructive peek |
| v22.0.0a4 | +673 / -1 | `/jobs` UI page + 3 new `/api/delegated-jobs*` endpoints |
| v22.0.0 GA | +30 / -3 | Drop alpha; README/architecture sweep; final retro |

Total: ~2350 LOC + retro arc across 5 ships on `feat/v22.0-async-delegate`.

## Capabilities (this sprint)

### MCP surface

- `delegate_task(name, task, deliverable, allow_writes=False, host=None, model=None, mode="sync", inbox_id="default")`
  - `mode="sync"` blocks until done (existing v1 behaviour, default).
  - `mode="async"` enqueues a row in `delegated_jobs` and returns a
    handle string. A daemon-thread worker picks queued rows in FIFO
    order via atomic `UPDATE ... RETURNING`.
  - `allow_writes=True` swaps the prompt suffix from "Read-only mode.
    Do NOT edit files." to "You may edit files. Make the change
    directly, then return a markdown summary listing files changed,
    new tests added, follow-ups left for the operator."
- `get_delegated_task(job_id) -> dict` — status of one async job
  (returns `status`, `output`, `error`, `cid`, timestamps,
  `duration_ms`, `allow_writes`, `inbox_id`, ...). Returns
  `{"error": "not_found", "job_id": <id>}` for unknown ids.
- `recall_pending_results(inbox_id, mark_read=True, limit=50) -> dict`
  — drain inbox. Returns `{inbox_id, results, marked_read}`. Results
  ordered by `completed_at ASC` (FIFO on completion order). Set
  `mark_read=False` for a non-destructive peek.

### Storage

- New SQLite table `delegated_jobs` (id, inbox_id, project, host,
  task, deliverable, allow_writes, model, status, output, error,
  cid, queued_at, started_at, completed_at, duration_ms, read_at).
  Default path `~/.harbormaster/delegated_jobs.db`; override via
  `$HARBORMASTER_JOBS_DB`.
- Restart recovery: on subsystem init, any `running` row from a
  previous process is marked `failed` with `error="server_restart"`.

### UI

- `/jobs` page with status filter chips (All / Queued / Running /
  Completed / Failed). Inline expand for full output/error per the
  v21.0.8 lazy-fetch pattern. Live counter strip queries
  `/api/delegated-jobs/summary`.
- Cmd-K command palette gains a "Delegated jobs" entry.

## Numbers

- 5 ships on `feat/v22.0-async-delegate`, alpha-by-alpha cadence
  with CI on every push.
- 1937 → 1977 tests (+40 net). mypy --strict clean on 66 source files.
  ruff src/ tests/ clean. No `# type: ignore` regressions, no `noqa`
  carried in.
- 0 backwards-incompatible changes — every pre-v22 caller of
  `delegate_task` keeps the same contract.

## Lessons

### Hardcoded error strings outlive their version

The `"disabled in v1"` message in `delegate.py` sat untouched from
v1.0.0 through v21.0.9. It was a placeholder waiting for the v2
approval gate; the gate never came. Downstream agents pattern-matched
on the string and built their playbooks around it ("delegate with
allow_writes=False, ask for diff, apply manually"). The placeholder
became a hard architectural assumption.

**Rule:** when a docstring or error string references a version-gated
"will be lifted in vN", file a follow-up task at write time. Otherwise
the placeholder becomes the ceiling.

### `bypassPermissions` was always on; only the prompt gated writes

The lift required zero subprocess changes. `claude -p
--permission-mode bypassPermissions` was already passed for both
`ask_project` and `delegate_task`; the v1 fail-closed was a
prompt-string guard plus an early `return`, not a permissions
barrier. Discovering this in a1 simplified a2–a4 considerably —
nothing under the prompt layer needed touching.

### `UPDATE ... RETURNING` for atomic claim

The first sketch had `SELECT id WHERE status='queued' LIMIT 1`
followed by `UPDATE WHERE id = ?`. Trivially racy under
multiple-worker. SQLite ≥ 3.35 supports `UPDATE ... RETURNING`, which
closes the window: pick the row and flip its status in one
statement. The
`test_claim_next_queued_is_atomic_across_threads` unit test fires 10
concurrent claims against 20 queued rows and asserts no double-claim;
would have failed on the racy first sketch.

### Late imports break circular paths from the surface in

`tools.delegate` imports `jobs.get_subsystem`. `jobs.worker` imports
`tools._grounding`. `tools.__init__` imports `tools.delegate`. At
module-import time this is cyclic. Moving the `get_subsystem` import
inside the tool body (instead of module-top) defers it past the cycle.
Captured as a load-bearing comment so a future contributor won't
"clean it up" back to a top-level import.

### Inbox identity stays string-only for v22

The simplest workable identity model: a free-form string, no auth.
Suits the local-MCP threat surface where harbormaster-mcp is spawned
by the calling Claude Code session. Cross-tenant inbox isolation (a
real concern for the HTTP daemon when it's eventually exposed beyond
loopback) is a forward extension — the `inbox_id` column is already
in the schema, so it's a config-driven gate rather than a breaking
change.

### Two read shapes for one store

The dashboard list (`/jobs` page) orders by `queued_at DESC` —
newest-first, operator-friendly. The inbox tool orders by
`completed_at ASC` — FIFO on completion, agent-friendly. Same
`JobStore`, two distinct read methods. Pre-thinking this in a2 saved
having to retrofit two views over a single query in a4.

## Carry-over (deferred from v22)

These are explicit non-goals for v22.0.0 — captured here as
candidate v22.x or v23 work:

1. **Multi-worker concurrency.** Worker count is 1 process-wide.
   Multi-worker is straightforward (spawn N `JobWorker` against the
   same `JobStore`; atomic claim handles the rest) but needs a config
   knob and a doc on when to bump it.
2. **SSE-streamed counter strip.** The dashboard counter refreshes on
   manual reload only. The `/api/network/stream` pattern would fit;
   deferred until an operator hits this as friction.
3. **Cross-tenant inbox isolation.** Trust model is "same MCP process
   = same trust boundary". Revisit when the HTTP daemon is exposed
   beyond loopback in a multi-user setup.
4. **Webhook-based notification.** Polling-only for v22. A FleetQ
   Bridge push (when a job completes) is plausible if operators
   prefer push over poll.
5. **Auto-commit option.** v22 has the subagent edit files but not
   git-commit; operator reviews and commits. A future
   `auto_commit=True` flag could close that loop. Stay opt-in to
   keep the safety default loud.

## Cumulative session totals (v3 + v4 + v5 + v6 + v21 patches + v22)

- **39 published PyPI versions** across 5 GA lines + 2 v6 patches
  + 7 v21 patches + v22.0.0a1-a4 + v22.0.0 GA.
- **7 successful monolithic-alpha-line releases** (v2.0, v2.1, v3.0,
  v4.0, v5.0, v6.0, v22.0) — v22 follows the same alpha-by-alpha
  cadence as the v3-v6 lines.
- 554 → 1977 unit + integration tests across the project lifetime
  (+1423, +257% from v2.1.0 GA baseline).
- mypy --strict + ruff clean throughout (46 → 66 source files).
- 0 force-pushes to main, 0 PyPI yanks, 0 backwards-incompatible
  changes within a GA line.

## Operator-facing upgrade note

After upgrading to v22.0.0:

- Default behaviour for every existing `delegate_task` caller is
  unchanged — `allow_writes=False, mode="sync"` is the same shape as
  v21.
- To use async: `delegate_task(..., mode="async", inbox_id="<name>")`
  returns a handle string; poll with `get_delegated_task(job_id)` or
  drain with `recall_pending_results(inbox_id)`.
- New SQLite DB at `~/.harbormaster/delegated_jobs.db` is created on
  first async-delegate or status-tool call (not at server boot). Safe
  to delete to reset state — schema is recreated on next call.
- The dashboard daemon and stdio MCP processes use the same DB. If
  the daemon is upgraded before stdio sessions restart, the
  dashboard sees the JobStore as empty until a stdio session fires
  an async call.

The retro arc for the v22 sprint lives in:

- [`docs/sprint-retro-harbormaster-v22.0.0a1.md`](./sprint-retro-harbormaster-v22.0.0a1.md)
- [`docs/sprint-retro-harbormaster-v22.0.0a2.md`](./sprint-retro-harbormaster-v22.0.0a2.md)
- [`docs/sprint-retro-harbormaster-v22.0.0a3.md`](./sprint-retro-harbormaster-v22.0.0a3.md)
- [`docs/sprint-retro-harbormaster-v22.0.0a4.md`](./sprint-retro-harbormaster-v22.0.0a4.md)
- this file (GA close)

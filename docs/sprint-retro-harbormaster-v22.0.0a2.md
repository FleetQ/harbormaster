# Sprint Retro — Harbormaster v22.0.0a2

**Date:** 2026-05-12
**Theme:** Built the async delegate path — agent A can now fire-and-forget
work and poll for the result later. New `harbormaster.jobs` package
(schema + store + worker + subsystem), new `get_delegated_task` MCP
tool, `delegate_task(mode="async")` parameter. Inbox-listing tool
(`recall_pending_results`) and UI surface come next.

## What landed

### `harbormaster` (this repo)

| File | Lines | Subject |
|---|---:|---|
| `src/harbormaster/jobs/__init__.py` | +24 | package surface (Job, JobStore, JobWorker, get_subsystem) |
| `src/harbormaster/jobs/schema.py` | +33 | SQLite DDL + status constants |
| `src/harbormaster/jobs/store.py` | +234 | thread-safe CRUD + atomic claim + orphan recovery |
| `src/harbormaster/jobs/worker.py` | +143 | daemon-thread worker, prompt builder, cid extract |
| `src/harbormaster/jobs/subsystem.py` | +78 | process-singleton init + shutdown |
| `src/harbormaster/tools/delegate.py` | mode= | adds `mode="sync"|"async"` + `inbox_id` parameters |
| `src/harbormaster/tools/job_status.py` | +37 | `get_delegated_task` MCP tool |
| `src/harbormaster/tools/__init__.py` | +1 | register `get_delegated_task` |
| `tests/unit/test_jobs_store.py` | +194 | 10 CRUD + atomicity tests |
| `tests/unit/test_jobs_worker.py` | +190 | 7 worker + subsystem-lifecycle tests |
| `tests/integration/test_jobs_e2e.py` | +112 | 3 fake_claude e2e tests |
| `src/harbormaster/__init__.py` | bump | 22.0.0a1 → 22.0.0a2 |

## Capabilities

- `delegate_task(name, task, deliverable, allow_writes, host, model, mode="sync"|"async", inbox_id="default")`:
  - `mode="sync"` is the existing v22.0.0a1 behaviour (default).
  - `mode="async"` enqueues a row in `delegated_jobs`, returns
    immediately with a handle string of the form
    `"queued d_<hex> (inbox=<id>). Poll with get_delegated_task('d_<hex>') or fetch completed results with recall_pending_results(inbox_id='<id>')."`
- `get_delegated_task(job_id) -> dict` returns the full row as a JSON
  dict (status, output, error, cid, timestamps, duration_ms,
  allow_writes, inbox_id, ...). Returns `{"error": "not_found",
  "job_id": <id>}` for unknown ids — distinguishable by missing
  `status` key.
- Background daemon thread picks `queued` rows in FIFO order via
  atomic `UPDATE ... RETURNING`, calls `run_backend` (the same helper
  the sync path uses, so QA log + writeback + KG triple extraction
  all still fire), then marks `completed` or `failed`. The cid is
  extracted from `run_backend`'s `Error: ... [cid=...]` failure shape
  so the inbox match the sync-call error format.
- On subsystem init, any `running` row from a previous process is
  marked `failed` with `error="server_restart"` so a crashed harbormaster
  doesn't leave zombie status forever.

## Numbers

- 12 files changed/added on `feat/v22.0-async-delegate`. ~1100 lines
  insertions over a1.
- 1937 → 1957 unit + integration tests (+20). `mypy --strict` clean
  on 65 source files. `ruff check src/ tests/` clean.

## Design notes / decisions

### One worker, one process

Each MCP-server process spawns one daemon thread on first async call.
Worker concurrency is 1 — runs jobs FIFO. Increase by instantiating
multiple `JobWorker` against the same `JobStore`; the
`UPDATE ... RETURNING` claim is atomic so they will not race.

This is intentional for v22.0.0a2: it keeps the failure mode obvious
(one job at a time → if it's slow, the next sits queued). Multi-worker
is a future config knob, not an alpha-1 scope decision.

### SQLite + thread lock instead of asyncio

FastMCP doesn't expose a startup hook in `server.py` and exposing one
would mean restructuring boot. A daemon thread sidesteps that — the
worker lives independently of the MCP loop, talks to SQLite (with WAL
+ thread lock) like any other long-lived background task.

`run_backend` is sync anyway (subprocess.run / Popen under the hood),
so async-ing the worker bought us nothing.

### Lazy init via module-level singleton

Tools call `harbormaster.jobs.get_subsystem(config)` instead of being
handed the store/worker by `register_tools`. First call opens the DB,
runs `recover_orphaned`, starts the worker. Subsequent calls return
the cached bundle. Tests reset between cases via `shutdown_subsystem`.

This avoids touching `server.py`'s tiny boot path.

### Late import to break a circular path

`delegate.py` and `job_status.py` import `get_subsystem` _inside_ the
tool body, not at module top. The chain
`tools.delegate → jobs → jobs.worker → tools._grounding →
tools.__init__ → tools.delegate` is cyclic at module-import time;
deferring the import to first call breaks it.

Captured in code as a load-bearing comment so a future contributor
won't move the import back to the top "for cleanliness".

## Lessons

### `UPDATE ... RETURNING` for atomic claim

The first sketch had `SELECT id WHERE status='queued' LIMIT 1`
followed by `UPDATE WHERE id = ?`. Trivially racy under
multiple-worker. SQLite supports `UPDATE ... RETURNING` (since 3.35),
which closes the window: pick the row and flip its status in one
statement. The unit test `test_claim_next_queued_is_atomic_across_threads`
fires 10 concurrent claims against 20 queued rows and asserts the
union of claims equals the set of enqueued ids — would have failed
on the racy first sketch.

### Error string shape matters, don't reshape lightly

`run_backend` returns `"Error: ... [cid=<hex>] — code=<code>: <msg>"`.
The async worker has to parse out the cid to populate the
`delegated_jobs.cid` column so the inbox surface matches the sync-call
error shape. A small `_extract_cid` helper does this. Three previous
sprints (v21.0.7's failure-context capture, v21.0.6's success-path
logging, and the integration tests in `test_e2e_fake_claude.py`) all
pattern-match on the literal `Error:` prefix and the bracketed cid —
treating this shape as a soft schema saved us from reinventing the
contract.

### Test the orphan-recovery path early

`recover_orphaned` runs once on subsystem init. Easy to forget on the
"happy path" build. The unit test
`test_recover_orphaned_promotes_running_to_failed` injects two rows
in `running` status (via consecutive `claim_next_queued`), then calls
`recover_orphaned` and asserts both flip to `failed` with reason
`server_restart`. Cheap, catches the silent-corruption-after-crash
regression class.

## Carry-over to v22.0.0a3 (inbox tool)

- `recall_pending_results(inbox_id, mark_read=True, limit=50)` MCP
  tool. Reads `JobStore.list_pending_for_inbox` (already implemented
  in a2), returns list of completed/failed jobs, optionally marks
  them read so they don't re-appear.
- Convention for `inbox_id`: caller chooses any non-empty string. No
  identity / auth — local-MCP threat model assumes any caller in the
  same process has full access to all inboxes.

## Carry-over to v22.0.0a4 (UI surface)

- `/jobs` HTML page listing rows from `delegated_jobs` with status
  filter chips. Lazy-fetch full output per v21.0.8 pattern.
- Dashboard counter `{queued, running, completed_today, failed_today}`
  via new `/api/delegated-jobs/summary` endpoint.
- Async-wrap any sync FS work per v21.0.3.

## Carry-over to v22.0.0 GA

- Drop alpha designation.
- Comprehensive retro covering a1+a2+a3+a4 arc.
- README "Status: stable" bump.
- Bump architecture doc section on `delegate_task` to reflect the
  full sync/async + inbox surface.

## Operator-facing note

After upgrading to v22.0.0a2, agents that previously called
`delegate_task` synchronously continue to work unchanged. To use the
new async path:

```
delegate_task(
    name="zonex", task="...", deliverable="...",
    allow_writes=True, mode="async", inbox_id="sprint-22",
)
# → "queued d_a8f3e2b14c00 (inbox=sprint-22). Poll with ..."
```

then later:

```
get_delegated_task(job_id="d_a8f3e2b14c00")
# → {"status": "completed", "output": "...", "duration_ms": 12345, ...}
```

Multiple async jobs to different projects run **serially** in v22.0.0a2.
Multi-worker concurrency is a v22.0.x or v23 knob.

# Sprint Retro — Harbormaster v22.0.0a3

**Date:** 2026-05-12
**Theme:** Closed the agent-A → agent-B inbox loop. New
`recall_pending_results` MCP tool: agent A polls one inbox and drains
every completed/failed async job at once, optionally peeking without
consuming.

## What landed

| File | Subject |
|---|---|
| `src/harbormaster/tools/inbox.py` | new — `recall_pending_results` MCP tool |
| `src/harbormaster/tools/__init__.py` | registers the new tool |
| `tests/integration/test_jobs_inbox.py` | 4 fake_claude e2e tests |
| `tests/unit/test_tools.py` | asserts new tool in registry |
| `src/harbormaster/__init__.py` | 22.0.0a2 → 22.0.0a3 |
| `docs/sprint-retro-harbormaster-v22.0.0a3.md` | this file |

## Capabilities

- `recall_pending_results(inbox_id="default", mark_read=True, limit=50) -> dict`
  - Returns `{"inbox_id": <id>, "results": [<job_dict>, ...], "marked_read": <int>}`
  - `results` is sorted by `completed_at` ascending — oldest first
    (FIFO), so a polling agent processes jobs in completion order.
  - `mark_read=True` (default) consumes the inbox; subsequent polls
    skip the same rows.
  - `mark_read=False` is a non-destructive peek — useful for UIs and
    debugging.

## Numbers

- 6 files (5 new, 1 modified). ~150 LOC.
- 1957 → 1961 tests (+4). mypy --strict on 66 source files clean.
  ruff src/ tests/ clean.

## Design notes

### Identity model: caller-supplied string

`inbox_id` is a free-form non-empty string. Any caller in the same
MCP process can read any inbox. This is the simplest workable model
for the local-MCP threat surface: harbormaster-mcp is spawned by the
calling Claude Code session, so the trust boundary is the OS process,
not the inbox name.

For cross-machine / multi-tenant inbox isolation (a real concern when
harbormaster-mcp runs as a shared HTTP daemon receiving requests from
multiple users), revisit in v23. The schema already carries
`inbox_id` so the storage layer is forward-compatible.

### FIFO order

`list_pending_for_inbox` orders by `completed_at ASC` — oldest
completion first. Agent A processes jobs in the order they finished,
not in the order they were enqueued. This matters when long jobs and
short jobs share an inbox: a short job that completed first appears
first regardless of enqueue order, which is the order a human
operator typically wants.

### Peek vs consume

`mark_read=False` is a one-flag toggle, not a separate tool. Keeps
the surface area small and lets the UI surface (v22.0.0a4) reuse the
same tool — render-without-consume via `mark_read=False`,
mark-as-read explicitly when the operator clicks.

## Carry-over to v22.0.0a4 (UI surface)

- `/jobs` HTML page reading from `recall_pending_results(mark_read=False)`
  for non-destructive display, plus an explicit "Mark all read"
  button that calls `mark_read=True` once.
- Dashboard counter `{queued, running, completed_today, failed_today}`
  via a new `/api/delegated-jobs/summary` HTTP endpoint that bypasses
  the inbox concept (it's process-wide, not per-inbox).
- Lazy-fetch full output per v21.0.8 pattern.

## Carry-over to v22.0.0 GA

- Drop alpha designation, comprehensive retro covering a1+a2+a3+a4 arc.
- README "Status: stable" bump.
- Update architecture doc with the full sync/async + inbox surface.

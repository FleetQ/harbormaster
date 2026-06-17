# Architecture + Test Plan — Resilient Orphan Recovery

**Feature branch:** `feat/resilient-orphan-recovery`
**Origin:** eve research → Workflow SDK spike (`claudedocs/spikes/`)
**Status:** Plan (sprint: think ✓ via spike → plan → build → test → ship)

## Problem (confirmed in code)

`JobStore.recover_orphaned()` (`src/harbormaster/jobs/store.py:769`) runs once per
process boot and does a blanket `running → failed (server_restart)`. A crash, a
launchd reap, or a deploy therefore **discards every in-flight delegated job** and
forces the operator to re-delegate. This is the durability gap the eve/Workflow-SDK
research targeted.

## Why NOT a step-event-log engine (scope decision)

The spike prototype demonstrated the SDK's step-checkpoint/replay pattern. But a
harbormaster job's work is a **single opaque `claude -p` subprocess** — there are
no intermediate Python steps to checkpoint, and half an LLM run cannot be replayed
deterministically. A generic event-log engine would be infrastructure with nothing
to record. The durability unit that actually exists here is **the whole job**.

So we implement the SDK's *intent* ("resume instead of lose") at the only boundary
that is real: re-running the job from scratch when that is safe.

## Design

Replace destructive orphan recovery with a **safety-classified** recovery at boot:

| Orphaned `running` job | New action | Why |
|---|---|---|
| `allow_writes = 0` (read-only) AND `recovery_count < MAX` | → `queued`, `recovery_count += 1` | Re-running a read-only ask has no side effects; the worker re-claims it. No re-delegation needed. |
| `allow_writes = 1` (writes) | → `failed` (`server_restart: write job, partial edits may exist — re-delegate manually`) | The dead subprocess may have applied partial edits; auto-rerun risks double-applying. A human decides. |
| `recovery_count >= MAX` (read-only) | → `failed` (`server_restart: exceeded recovery attempts`) | A job that reliably crashes the worker must not re-queue forever (poison-pill guard). |

- `MAX_RECOVERY_ATTEMPTS = 1` — a module constant in `store.py` (re-queue once, then
  fail). Not a config knob — YAGNI until an operator asks.
- New column `recovery_count INTEGER NOT NULL DEFAULT 0` via the existing idempotent
  `MIGRATIONS` mechanism (fresh + existing DBs, no backfill).
- `recover_orphaned()` returns `OrphanRecovery(requeued: int, failed: int)` instead
  of a bare int, so `subsystem.get_subsystem` logs both outcomes honestly.
- Re-queued rows keep their original `queued_at` (fair ordering — they were first);
  `claim_next_queued` overwrites `started_at` on re-claim.

### Files touched

- `jobs/schema.py` — add `recovery_count` migration entry.
- `jobs/store.py` — `MAX_RECOVERY_ATTEMPTS` const; `OrphanRecovery` dataclass;
  rewrite `recover_orphaned()`.
- `jobs/subsystem.py` — update the boot log to report requeued + failed.

`recovery_count` stays an internal column (read/written only inside
`recover_orphaned`); it is intentionally NOT added to the `Job` dataclass / `as_dict`
to keep blast radius minimal (no UI / snapshot-test churn).

## Test plan

Edit `tests/unit/test_jobs_store.py`:

1. **Rewrite** `test_recover_orphaned_promotes_running_to_failed` → split intent:
   - read-only running job → re-queued (`status == queued`, `recovery_count == 1`,
     no error), and a subsequent `claim_next_queued()` re-claims it.
2. **New** `test_recover_orphaned_fails_write_jobs`: `allow_writes=True` running job
   → `failed`, error mentions write/partial edits, never re-queued.
3. **New** `test_recover_orphaned_caps_requeue`: read-only job recovered twice →
   first boot re-queues (`recovery_count==1`), second boot (still running) → `failed`
   with `exceeded recovery attempts`.
4. **New** `test_recover_orphaned_return_summary`: mixed batch → `OrphanRecovery`
   counts (`requeued`, `failed`) correct.
5. Migration sanity: fresh store exposes `recovery_count` column defaulting to 0.

### Acceptance criteria

- Read-only in-flight job survives a simulated restart and completes on re-run.
- Write in-flight job is failed (not silently re-run).
- No infinite re-queue under repeated crashes.
- Full suite green (`pytest -q`), including the existing `test_jobs_*` and
  `test_subsystem` paths.

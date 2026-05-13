# Sprint Retro — Harbormaster v24.0.0a1

**Date:** 2026-05-13
**Theme:** Open the v24 line with multi-worker JobWorker concurrency
— atomic claim ready since v22.0.0a2; just needed the config knob.

## What landed

| File | Subject |
|---|---|
| `src/harbormaster/config.py` | new `DelegateConfig.worker_count: int = Field(default=1, gt=0, le=16)` |
| `src/harbormaster/jobs/subsystem.py` | spawns N workers per config; `Subsystem.workers: list[JobWorker]`; backward-compat `worker` property returns first worker |
| `tests/unit/test_jobs_multiworker.py` | new — 4 tests: configured count, default=1, no-double-claim under load, clean shutdown |
| `docs/operator-config-reference.md` | new `[delegate]` section documenting `retain_recent_k` + `worker_count` |
| `src/harbormaster/__init__.py` | 23.0.0 → 24.0.0a1 |
| Tier 1 housekeeping (bundled) | `plugins.py:58` + `routes.py:3117` deferred-comment cleanup; stdio zombie killed |

## Numbers

- 6 files (3 new, 3 modified). ~80 net LOC.
- 2013 → 2017 tests (+4 multiworker tests). mypy --strict clean.
  ruff clean.

## Design notes

### `Subsystem.workers: list[JobWorker]` + `worker` compat property

Renamed singular `Subsystem.worker` → `workers: list[JobWorker]`. To
preserve compatibility with v22+ code that reads `sub.worker`
(test_jobs_sse_stream.py, manual operator inspection), added a
`@property` returning `workers[0]`. Sufficient for read-only
inspection (is_alive checks etc); for lifecycle control, callers
explicitly iterate `workers`.

### Default = 1 worker (backward compat)

`worker_count: int = Field(default=1, gt=0, le=16)`. Operators on
bare defaults see identical behaviour to v22/v23 (single worker,
serial processing). Multi-worker is opt-in via TOML:

```toml
[delegate]
worker_count = 4
```

Hard cap 16 mirrors `fleetq.dispatcher_max_workers` — prevents an
operator typo'd `worker_count = 1000` from spawning a thread storm.

### Atomic claim already worked

No JobStore changes needed. The v22.0.0a2
`UPDATE delegated_jobs SET status='running', started_at=NOW()
WHERE id = (SELECT id FROM ... WHERE status='queued' ORDER BY
queued_at ASC LIMIT 1) RETURNING *` atomically picks one row.
Regression-guarded by `test_claim_next_queued_is_atomic_across_threads`
(10 concurrent claims, 20 queued rows, asserts each id claimed
exactly once).

v24.0.0a1's new test
`test_multi_worker_processes_all_jobs_without_double_claim` extends
this from raw store-level claims to full worker-loop processing:
25 jobs / 4 workers / fake run_backend → exactly 25 entries in the
claim log, sorted equal to the enqueue order.

## Tier 1 bundled

Pre-v24 housekeeping included in this commit:

1. `plugins.py:58` docstring — was "deferred to v2.0.0a5+", now
   "shipped v2.0.1"
2. `routes.py:3117` comment — removed "future v11 deferred" gold-
   plating speculation; documented intent as "stays out of scope —
   not a real friction point"
3. stdio zombie process pid 33667 killed
4. `[delegate]` section added to operator-config-reference.md
   (also documents v23.0.0a2's `retain_recent_k`)

## Operator-facing note

After upgrading to v24.0.0a1:

- **No new endpoints, no signature changes.** Single-worker default
  preserved.
- To enable multi-worker, add to TOML:
  ```toml
  [delegate]
  worker_count = 4
  ```
  Restart daemons (kickstart). Logs will show
  `delegate-job subsystem ready at ... (workers=4)` instead of
  `(workers=1)`.
- Multi-worker is useful when you regularly delegate >5 jobs
  concurrently to the same inbox/fan-out. Single-worker stays
  appropriate for sequential workflows where order-of-completion
  matters.

# Sprint retro — harbormaster v21.0.0a8

**Phase 8 of 10 in the v21.0.0 alpha series.**
Architectural cluster: multi-process metrics aggregator + cross-process
projects cache. Both items were long-deferred — Part A from v9.0.0a2,
Part B from v7.0.0a6. They landed together because they share the
same underlying motivation: harbormaster runs as more than one process
(``harbormaster-mcp`` stdio/HTTP + ``harbormaster-ui``), and per-process
in-memory state has been silently producing partial views of the world.

## What shipped

### Part A — multi-process metrics aggregator

A SQLite-backed counter store at ``~/.harbormaster/dispatcher_metrics.db``.
Every dispatcher counter mutation (in-flight, total_completed,
total_failed, last_dispatched_at) is now mirrored to the shared DB on
top of the in-process counters.

* New module: ``harbormaster.dispatcher_metrics_store.DispatcherMetricsStore``.
  WAL mode, 5s busy-timeout, atomic ``INSERT ... ON CONFLICT DO UPDATE``
  for every mutation. No external lock — SQLite's own locking handles
  multi-writer contention.
* ``DispatcherStats.snapshot()`` now returns the cross-process tools
  map and active_workers count when the store is reachable. ``running``
  stays in-process (each process only knows its own live spans). The
  in-process counter dict is retained as a fallback when the store is
  unreachable (read-only home dir, etc.) so the API surface never
  breaks.
* No new public endpoint — ``/api/dispatcher/status`` payload shape is
  unchanged; the values just get more honest.

### Part B — cross-process projects cache

``ProjectsCache`` (v7.0.0a6) gains an optional ``persist_path``. When
set, the cache reads and writes ``~/.harbormaster/projects_cache.json``
as a shared backing store.

* Writes are atomic via tmpfile + ``os.replace``, serialised across
  processes by an advisory ``fcntl.flock`` on a sidecar
  ``projects_cache.json.lock`` file.
* Wall-clock timestamps for TTL comparison (monotonic time can't cross
  process boundaries).
* mtime-signature check still invalidates on project-dir changes.
* Corrupt files don't crash readers — JSON errors fall through to the
  builder.

The route in ``routes.py::list_projects`` now constructs
``ProjectsCache(persist_path=default_persist_path())`` so the
production UI is on the new code path. The MCP process can opt in by
constructing its own ``ProjectsCache`` against the same file.

## Tests

* ``tests/ui/test_v21_multiproc_metrics.py`` — 7 tests covering
  round-trip, decrement-clamp, concurrent writers (4 threads ×
  25 increments, asserts 100 final), separate-store instances seeing
  each other's writes, WAL mode assertion, end-to-end
  ``DispatcherStats.snapshot()`` reading peer-process writes.
* ``tests/ui/test_v21_crossproc_projects_cache.py`` — 7 tests covering
  process-restart survival, atomic JSON validity, mtime invalidation,
  wall-clock TTL, two readers seeing consistent data, ``invalidate()``
  removing the on-disk file, corrupt-file recovery.

All 45 existing tests in ``test_manifest_cache.py``,
``test_dispatcher_status_endpoint.py``, ``test_dispatcher_trace_endpoint.py``
still pass — no behavioural regression.

## What worked

* **Dual-write + read-through**: keeping the in-process counter dict
  intact and only consulting the SQLite store inside ``snapshot()``
  meant zero behaviour change for callers that don't go through the
  status endpoint, while the UI route picks up the cross-process view
  for free.
* **WAL mode + busy-timeout** removed the need for an external lock on
  the metrics DB. The concurrent-writer test (4 threads × 25 increments
  → 100 final) confirms SQLite handles the contention.
* **fcntl.flock on a sidecar** rather than the cache file itself means
  the atomic rename and the lock release are independent — readers
  never wait on a write lock, and writers don't block on reader open()
  calls.

## What we deferred (intentionally)

* **MCP-side ProjectsCache wiring**. The route in ``routes.py``
  (UI process) is on the new path; the MCP-process code paths that
  call ``discover_projects()`` directly still bypass the cache. They
  can opt in by reusing the ``ProjectsCache`` instance — left as a
  v21.x cleanup because the immediate benefit (the UI no longer
  re-walks across restarts) was the load-bearing fix.
* **Cross-process span aggregation**. The completed-spans ring and
  running list are still per-process. The waterfall surface is a UI
  feature and the UI is the only consumer; merging spans across
  processes would require a separate event-log table and is a
  separate phase.
* **Operator-visible diagnostic** for the cache + DB files (e.g.
  ``GET /api/diagnostics/storage``). The two files are documented in
  this retro; surfacing them in the UI is cosmetic and can wait.

## Migration

None. Existing installs gain the new files on next startup:

* ``~/.harbormaster/dispatcher_metrics.db`` (mode 0600, WAL + ``-shm`` + ``-wal`` sidecars)
* ``~/.harbormaster/projects_cache.json`` (mode 0644 by default umask)

Both are safe to delete at any time — they're caches, not source of
truth.

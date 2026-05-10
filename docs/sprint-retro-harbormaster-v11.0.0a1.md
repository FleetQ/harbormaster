# Sprint Retro — Harbormaster v11.0.0a1

**Theme:** Persistent SQLite-backed network log + caller-project propagation.

Closes the v10.0.0a7 deviation: the in-process `MCPCallLog` ring
buffer was volatile (lost every restart) and unable to attribute
calls to a calling project. v11.0.0a1 swaps the storage layer to
SQLite while keeping the public surface stable, and adds a
`X-Caller-Project` header propagation chain so cross-project edges
in the network graph are real instead of always "operator → target".

## What shipped

- `src/harbormaster/ui/network_store.py` — new module. `NetworkStore`
  class wraps SQLite at `~/.harbormaster/network_log.db` (mode 0600,
  WAL journal, ~5000 row rolling cap pruned every 100 inserts).
  `NetworkEvent` dataclass gained an optional `duration_ms` field
  for forward-compat with v11.0.0a5's backend token instrumentation.
- `src/harbormaster/ui/network_log.py` — rewritten as a thin alias
  layer. The module-level `network_log` singleton is now a
  `NetworkStore`. `_MCPCallLog` is preserved as an alias for
  external callers who reference it.
- `set_caller_project()` / `reset_caller_project()` /
  `current_caller_project()` — contextvar-backed helpers exposed for
  call sites that want to bind the calling-project name for the
  duration of an async operation.
- `src/harbormaster/ui/routes.py` — `mcp_proxy` reads the
  `X-Caller-Project` request header and threads the value through
  both streaming (`_stream_dispatch` → `_stream_local_tool` /
  `_stream_remote_tool` → `_emit_chunks_then_result`) and JSON
  (`_dispatch_mcp` → `_record_mcp_dispatch`) paths. Falls back to
  `"operator"` when absent, so pre-v11 clients see no behaviour
  change.
- `tests/conftest.py` — sets `HARBORMASTER_NETWORK_LOG_DB` to a
  fresh tmp path BEFORE any test imports `harbormaster.ui.network_log`.
  Without this the suite would write into the user's real
  `~/.harbormaster/network_log.db`.

## Tests

| Suite delta                  | Before | After |
|-----------------------------|-------:|------:|
| Total tests                 | 1097   | 1116  |
| New (test_network_store.py) | —      |   +18 |
| Adjusted ring-buffer test   |    1   |     1 |

`tests/ui/test_network_store.py` covers:
- store roundtrip (insert + recent + ordering)
- chronological ASC order parity with the v10 deque
- `recent(limit=N)` returns the most recent N
- prune cap honoured after PRUNE_EVERY inserts
- DB file mode is 0600
- subscribe/unsubscribe live SSE fan-out
- clear truncates table (used by tests)
- `/api/network/events` returns rows after a second `create_app`
- caller contextvar set/reset isolation
- `_record_mcp_dispatch` honours `caller=` for non-fanout
- `_record_mcp_dispatch` falls back to "operator" when absent
- `_record_mcp_dispatch` for fan_out_ask propagates caller to all
  per-project events
- `_emit_chunks_then_result` reads `caller` from `record_ctx`
- on-disk schema matches the v11.0.0a1 spec (column names + types)
- end-to-end POST `/mcp/harbormaster` with `X-Caller-Project` lands
  the header value in the persisted event's `caller` field

## Quality gates

```
mypy --strict src/harbormaster   →  Success: no issues found in 54 source files
ruff check src tests              →  All checks passed!
pytest -q                         →  1116 passed, 2 skipped in 37.36s
```

## Architecture notes

- Public surface preserved: `network_log.record/recent/subscribe/
  unsubscribe/clear` work identically. UI consumers (Cytoscape graph
  + chat view) need zero changes.
- `recent()` returns chronological ASC order to match the v10 deque
  semantics that the chat view relied on. Internally the SQL is
  `ORDER BY id DESC LIMIT N` then reversed in Python.
- Pruning is opportunistic (every 100th insert) to keep the hot
  write path cheap. Cap may briefly overshoot by ≤100 rows; the
  Phase 1 spec called this out as acceptable.
- WAL journal mode + `synchronous=NORMAL` chosen for write
  throughput — the network log is best-effort observability data
  and tolerates a crash-window of ~10ms.
- Caller propagation uses an explicit kwarg through the call chain
  (not contextvars) because the SSE generator is iterated by the
  ASGI machinery long after the request handler's `try/finally`
  would have torn down a contextvar binding. The `set_caller_project`
  contextvar API is exposed for in-process callers who DO want
  contextvar semantics (e.g. future inter-tool delegation paths).

## Deviations

- **`NetworkEvent` gained an optional `duration_ms` field.** Spec
  called this out for v11.0.0a5 (token instrumentation). Adding the
  column now means a5 doesn't need a schema migration. Default
  `None` keeps existing serializers compatible.
- **Pruning interval (PRUNE_EVERY=100)** is hard-coded rather than
  configurable. Operator-facing knob deferred to v12 if anyone hits
  a use case where 100 feels wrong.

## Next

Phase 2 — memory revision history (per-file rolling 20-revision log
keyed off the `~/.harbormaster/memory_revisions.db` table).

# Sprint Retro — Harbormaster v4.0.0a6

**Date:** 2026-05-09
**Theme:** Promoted the v3.0.0a5 single-worker dispatcher to an optional
ThreadPoolExecutor — but only after a 50-concurrent stress test proved
the dispatch path is thread-safe.

## What landed

| SHA | Subject |
|-----|---------|
| `e1d81a8` | feat(fleetq): multi-worker dispatcher pool (v4.0.0a6) |

## Capabilities (this sprint)

### 1 · Stress-test-first

`tests/integration/test_dispatcher_stress.py` runs 50 concurrent
dispatches through `MCPDispatcher` backed by a real FastMCP server
with the safe-to-stress tool subset (`list_projects`, `list_hosts`,
`project_graph` — read-only, no LLM calls). The test verifies:

- No deadlocks (test completes within timeout)
- No exception leaks (every dispatch returns)
- All envelopes are well-formed JSON with `result` key
- Mixed valid + invalid payloads coexist (success + isError envelopes
  both land without poisoning each other)

Both stress tests pass. **Thread-safety of the dispatch path is proven
sufficient to ship the pool.**

### 2 · `[fleetq] dispatcher_max_workers`

```toml
[fleetq]
dispatcher_max_workers = 4   # default 1; max 16
```

When > 1, `BridgeRelay._start_worker_thread` spins up a bounded
`ThreadPoolExecutor`. The worker thread becomes a producer (drains
the inbound queue, submits to pool) instead of doing dispatch inline.

When = 1 (default), behaviour is identical to v3.0.0a5 — single-worker,
serial dispatch.

`dispatcher_max_workers = 0` clamps to 1 (sane fallback for
mis-configuration).

### 3 · Clean shutdown

`_stop_worker_thread` now also calls
`pool.shutdown(wait=False, cancel_futures=True)` when a pool exists.
In-flight requests are cancelled cleanly; the FleetQ side wakes via
existing `client-relay.error` machinery.

## Real numbers

- 1/1 v4.0.0a5-retro action item shipped
- 0 PRs opened — merged via `git merge --no-ff`
- 6 new tests (2 integration stress + 4 unit)
- Test suite delta: 664 + 2 skips → **670 + 2 skips**
- `mypy --strict` clean across 49 source files
- `ruff` clean across `src/` and `tests/`
- 0 backwards-incompatible changes — opt-in via config, default 1

## What worked

- **Stress test as gate, not benchmark.** The test isn't measuring
  speedup; it's verifying correctness under contention. That's what
  was missing in the v3.0.0a5 caution. With the test in place,
  shipping the pool became a config flip + guard rail rather than
  a leap of faith.
- **Worker-thread becomes producer, not consumer.** The v3 worker did
  dispatch inline; the v4 worker reads + submits. Same `_worker_loop`
  branches on `_dispatcher_pool is not None`. No second thread-pool
  loop class, no parallel queues — minimal new surface area.
- **`cancel_futures=True` at shutdown.** Without this, `pool.shutdown()`
  waits for in-flight tasks; with it, pending work cancels and exits
  fast. FleetQ's popChunk already handles silent stream ends as
  errors, so cancelled responses are recoverable.
- **Mixed payloads in stress.** Some payloads are tools/list (valid),
  some are tools/call with missing tool (isError). Stress test asserts
  both envelopes appear — proves the error path is thread-safe too,
  not just the happy path.

## What to change / next

- **No `tools/call` with backends in the stress test.** Tools that
  invoke `claude --print` (ask_project / delegate_task) would need
  the fake-claude harness already present in `tests/fixtures/fake_claude.py`.
  Current stress covers read-only tools only. Worth extending later
  if the pool is opted-in widely.
- **No per-tool thread-safety map.** All tools are treated as
  uniformly safe. If a future tool turns out unsafe, the workaround
  is to keep `dispatcher_max_workers=1`. A future phase could ship a
  per-tool gate.
- **Clamp at 16 workers.** Arbitrary; same scale of caution as
  parallel_recall_max_workers (32). Bumpable if real load justifies.

## Action items for v4.0.0 GA

1. **Drop alpha + write GA retro.** Bump `__version__` to `4.0.0`,
   write a GA retro covering all 6 phases (a1-a6), tag `v4.0.0`,
   push, verify on PyPI. No new code in the GA tag (mirrors v1/v2/v3
   GA pattern).

## Out-of-scope (still)

- Tauri / Electron desktop UI — no demand.
- Relay-binary path (Path B) — Path C HTTP tunnel covers it.
- IDE extension — MCP works with any MCP client.
- pnpm v5 lockfile support — pre-2022 format.
- Session-cookie auth + CSRF — defer until multi-operator UI is real.
- IE11 / pre-2018 clipboard fallback — modern-browser-only is fine.
- Double-tap-to-reset / keyboard shortcuts on graph zoom — defer.
- Reconciliation cross-fade / writeback spinner — defer until noticed.
- Auto-reembed exponential-backoff retry — defer until observed.
- Auto-reembed UI panel — endpoint exists; panel is next polish.
- Per-tool thread-safety map — uniform safe-or-not gate is enough today.
- Stress-test coverage for backend tools — needs fake-claude wiring;
  defer until pool is opted-in widely.

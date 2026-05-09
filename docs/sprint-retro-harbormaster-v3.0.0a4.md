# Sprint Retro — Harbormaster v3.0.0a4

**Date:** 2026-05-09
**Theme:** Concurrency for `recall_qa(host="all")`. Opt-in thread-pool
fan-out for setups with several configured hosts; default behaviour
unchanged.

## What landed

### `harbormaster` (this repo)

| SHA | Subject |
|-----|---------|
| `7b7aa4b` | feat(recall): parallel cross-host recall via thread pool (v3.0.0a4) |

## Capabilities (this sprint)

### 1 · Parallel cross-host recall

`recall_qa(host="all")` previously walked every per-host sqlite store
sequentially. With the fastembed backend each store open dominates the
per-target latency (model warm-up + sqlite open + vec extension load).
For setups with 4-6 configured hosts the wall-clock added up.

After: bounded `ThreadPoolExecutor` fan-out when `[history]
parallel_recall = true` AND there is more than one target. Single-host
setups bypass the pool entirely (no point paying thread spawn cost
for one sequential call).

Config additions (both default conservative):

```toml
[history]
parallel_recall = false          # opt-in
parallel_recall_max_workers = 4  # 1..32
```

Response shape gains a `"parallel": bool` flag so callers can diagnose
which path actually ran:

```json
{
  "enabled": true,
  "host": "all",
  "hosts_searched": ["local", "friday", "jarvis"],
  "parallel": true,
  "matches": [...]
}
```

### 2 · Per-host failure isolation preserved

Each worker catches its own exceptions inside `_recall_one_host`; a
broken store on one host still surfaces in the `errors` map without
poisoning the merge. Tested explicitly under both sequential AND
parallel modes.

## Real numbers

- 1/1 v3.0.0a3-retro action item shipped
- 0 PRs opened — merged `feat/v3.0-parallel-recall` directly via `--no-ff`
- 4 new unit tests (parity, parallel-isolation, single-target bypass, default-off)
- Test suite delta: 597 + 1 skip → **601 + 1 skip**
- `mypy --strict` clean across 48 source files
- `ruff` clean across `src/` and `tests/`
- 0 backwards-incompatible changes — opt-in via config

## What worked

- **Capping workers at len(targets).** Spinning up 4 threads to query
  2 hosts is wasteful. `min(parallel_recall_max_workers, len(targets))`
  removes the lower-bound spin-up cost without giving up the upper
  bound for big fleets.
- **Inner closure captures the shared kwargs.** The `_one(target)`
  closure folds question + top_k + project + min_similarity + backend
  into the worker; `pool.map(_one, targets)` becomes one-line. Avoids
  passing six positional args through the fan-out boundary.
- **Diagnostic `parallel` flag.** Single source of truth for "did the
  pool actually run?" — which matters because the bypass for single-
  target setups would otherwise be invisible to operators.

## What to change / next

- **No measured speedup numbers in tests.** The unit tests verify
  *correctness parity*, not *latency improvement*. Adding a timing
  assertion would be flaky on CI; deferring real-world benchmark to
  manual measurement until the v3.0.0 GA.
- **fastembed model load is per-store.** The backend's `encode()` is
  called once per worker; if fastembed initialises lazily it might
  warm up multiple times in parallel — a hot spot for memory.
  Acceptable for now (each backend instance is held briefly inside
  `_recall_one_host`); flag if observed to balloon RSS.

## Action items for the next sprint (v3.0.0a5)

1. **Pysher worker-thread offloading.** The Pusher (Reverb) client
   shares the FastAPI event loop. Long-running event handlers (LLM
   triple extraction, KG writeback) can block the loop. Move pysher
   into a dedicated worker thread with bounded inbound/outbound
   queues, so the main loop stays responsive even when an MCP tool
   takes seconds.

## Out-of-scope (still)

- Tauri / Electron desktop UI — no demand.
- Relay-binary path (Path B) — Path C HTTP tunnel covers it.
- IDE extension — MCP works with any MCP client.
- pnpm v5 lockfile support — pre-2022 format.
- Cross-process file locking on bridge state — single-writer in practice.
- Latency benchmark harness for parallel recall — manual until GA.

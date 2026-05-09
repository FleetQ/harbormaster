# Sprint Retro — Harbormaster v6.0.0a5

**Date:** 2026-05-09
**Theme:** Last concurrency claim verified. Streaming path now stress-
tested under the v4.0.0a6 dispatcher pool just like non-streaming was.

## What landed

| SHA | Subject |
|-----|---------|
| `56673a1` | test(integration): streaming-chunks dispatcher stress |

## Capabilities

### 1 · Per-request ordering invariant

50 concurrent agent.requests, each handler yields 5 chunks (250 total
chunks across the publish surface). The test asserts:

- Each request emits exactly its 5 chunks
- Per-request, the chunk indices arrive in `[0, 1, 2, 3, 4]` order on
  the publish path

Different requests' chunks may interleave with each other in the
global capture order — that's expected with `dispatcher_max_workers=4`.
The contract is **per-request ordering**, not global.

### 2 · Mid-stream shutdown is clean

`stop()` while a long-running streaming handler is mid-iteration:

- No exception leaks
- No daemon thread pinned
- `_worker_thread_handle` and `_dispatcher_pool` both reset to None

Critical because `client-relay.error` machinery depends on cooperative
cleanup; a hung pool would mean dangling responses from FleetQ's POV.

### 3 · Capture-by-trigger pattern

The test stub channel intercepts `channel.trigger("client-relay.chunk", data)`
calls and records `(request_id, chunk_index, text)`. Handler emits
`f"{rid}:chunk-{i}"` so the test can recover the ordinal from the
captured text. Cheap, deterministic, doesn't require network or pysher.

## Real numbers

- 1/1 v6.0.0a4-retro action item shipped
- 0 PRs opened — merged via `git merge --no-ff`
- 2 new integration tests
- Test suite delta: 730 + 2 skips → **732 + 2 skips**
- `mypy --strict` clean across 49 source files
- `ruff` clean
- 0 backwards-incompatible changes — pure test addition

## What worked

- **Per-handler request_id embedding.** Without explicit (request_id,
  chunk_index) labelling, asserting "this chunk belongs to this
  request" would require tracking a queue per request. Embedding
  the IDs in the chunk text itself made the assertion a one-liner.
- **Tight inner sleeps (2ms).** Long enough to give other workers
  a chance to interleave; short enough to keep the test under 1s.
  Without the sleep, threads might be too fast for the OS to
  actually preempt — the test would pass trivially.
- **Reused fake_pusher_factory pattern.** Same MagicMock approach
  the unit relay tests use. Integration tests don't need a real
  pysher; they just need the channel.trigger surface to capture.

## What to change / next

- **No "chunk timing" assertion.** The test verifies ordering, not
  latency. A future stress could measure that chunks for a given
  request arrive within X ms of each other (regression guard for
  the worker thread doing something silly with locks). Defer.
- **No memory pressure test.** 250 chunks fits easily in memory.
  A real-world long-stream test (10K chunks) could surface a slow
  leak in the publish path. Defer.

## Action items for the next sprint (v6.0.0a6)

1. **`harbormaster-mcp dispatcher status` CLI.** Surface the
   v5.0.0a3 SAFE_FOR_PARALLEL allowlist + operator deny list at
   runtime, mirroring the v2.0.1 `plugins list` pattern.

## Out-of-scope (still)

- Tauri / Electron desktop UI — no demand.
- Relay-binary path (Path B) — Path C HTTP tunnel covers it.
- IDE extension — MCP works with any MCP client.
- Session-cookie auth + CSRF — defer until multi-operator UI is real.
- pnpm v5 lockfile support — pre-2022 format.
- Cancel-running-reembed button — defer until observed.
- Reembed run history — defer until needed.
- Per-host stale thresholds — defer until observed.
- Language badge on cards — defer.
- Auto-derived shortcuts array — defer.
- Page-aware popover filtering — defer until popover is global.
- Streaming chunk-timing assertion — defer.
- Memory-pressure stress (10K+ chunks) — defer until profiled.

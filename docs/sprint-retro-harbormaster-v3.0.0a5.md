# Sprint Retro — Harbormaster v3.0.0a5

**Date:** 2026-05-09
**Theme:** Decoupled the FleetQ relay's event-receive path from MCP tool
dispatch. pysher's thread no longer blocks on a slow handler.

## What landed

### `harbormaster` (this repo)

| SHA | Subject |
|-----|---------|
| `66b2911` | feat(fleetq): pysher worker-thread offloading (v3.0.0a5) |

## Capabilities (this sprint)

### 1 · Dedicated dispatcher thread

Before: `BridgeRelay._on_agent_request` called
`_dispatch_chunk_handler` synchronously on pysher's internal thread.
The chunk_handler from v3.0.0a1 dispatches MCP tool calls — some of
which (LLM-backed tools, KG writeback) take seconds. While the
handler ran, pysher's event-receive thread couldn't process new
agent.request events. They queued up in pysher's internal buffers
and arrived late.

After: a `bridge-relay-dispatcher` worker thread drains a
`queue.Queue(maxsize=64)` of `(request_id, payload)` tuples. pysher's
thread enqueues + returns in microseconds. The worker pops and runs
`_dispatch_chunk_handler`.

Single worker on purpose — MCP tools share state (sqlite stores, the
embedding backend in `recall_qa`, the bridge state writer) that is
not provably thread-safe. Serial dispatch from a queue gives ordered
processing without that surface area.

### 2 · Backpressure via bounded queue

When the queue fills (worker can't keep up), the relay does NOT block
pysher's thread. Instead:
- Publishes `client-relay.error` for the rejected `request_id`
- Logs at warning level
- Drops the request

The FleetQ-side `popChunk` sees the error and wakes its waiter cleanly
rather than timing out.

### 3 · Constructor flags

```python
BridgeRelay(
    ...,
    worker_thread=True,      # default — start the dispatcher thread
    worker_queue_max=64,     # bounded inbound queue
)
```

`worker_thread=False` keeps the v2.0.0a7 inline-dispatch behaviour.
Existing test fixtures relying on synchronous dispatch through stub
channels keep working unchanged.

## Real numbers

- 1/1 v3.0.0a4-retro action item shipped
- 0 PRs opened — merged `feat/v3.0-pysher-worker` directly via `--no-ff`
- 4 new unit tests (worker thread isolation, inline fallback, queue
  overflow, clean shutdown)
- Test suite delta: 601 + 1 skip → **605 + 1 skip**
- `mypy --strict` clean across 48 source files
- `ruff` clean across `src/` and `tests/`
- 0 backwards-incompatible changes — defaults preserve outward behaviour

## What worked

- **Sentinel-based shutdown.** Putting `None` on the queue is the
  classic Python pattern; the worker exits cleanly without thread.join
  timeouts when the system is idle, and degrades gracefully (logs +
  daemons-leak) when the worker is wedged. No SIGTERM trickery.
- **`worker_thread=False` escape hatch.** The existing test suite has
  ~37 relay tests that depend on synchronous dispatch through a stub
  channel. Adding the worker thread by default would have broken all
  of them. Making the new behaviour an opt-IN at construction time
  (with the production wire-up in `__main__.py` flipping the default)
  keeps the change safe.
- **Bounded queue + error envelope on overflow.** A naive unbounded
  queue would just trade one failure mode (slow events) for another
  (memory growth). Backpressure that converts overflow into a
  client-relay.error keeps the contract tight.

## What to change / next

- **Single-worker is conservative.** If we do prove thread-safety of
  the recall path + KG writer + bridge state writer, we can flip to
  a small pool. Defer until profile data shows it matters.
- **Queue-full error is publish-best-effort.** If the channel itself
  isn't ready (e.g. mid-disconnect) the error envelope might never
  reach FleetQ. Acceptable — the FleetQ side has its own popChunk
  timeout safety net.

## Action items for the next sprint (v3.0.0a6)

1. **Token plumbing for bearer-protected UI installs.** When
   `HARBORMASTER_UI_TOKEN` is set, the UI rejects unauthenticated
   calls. But internal UI routes that fan out to MCP tools (e.g.
   `/tools/fan-out` → `delegate_task`) currently miss the token
   plumbing. Add an internal-token resolver helper and route every
   internal MCP dispatch through it.

## Out-of-scope (still)

- Tauri / Electron desktop UI — no demand.
- Relay-binary path (Path B) — Path C HTTP tunnel covers it.
- IDE extension — MCP works with any MCP client.
- pnpm v5 lockfile support — pre-2022 format.
- Multi-worker dispatch pool — defer until thread-safety proven.

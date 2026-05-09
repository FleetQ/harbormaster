# Sprint Retro — Harbormaster v2.0.0a7

**Date:** 2026-05-09
**Theme:** Final v2 alpha. Per-token streaming through the FleetQ Bridge
— BridgeRelay grows a publish surface that emits `client-relay.chunk`
events back through the Pusher channel as multi-chunk responses.

## What landed

### `harbormaster` (this repo)

| SHA | Subject |
|-----|---------|
| (squash) | feat(fleetq): per-token streaming through Bridge (#21) |

## Capabilities (this sprint)

### 1 · `publish_chunk(request_id, chunk, done, usage)` + `publish_error(request_id, error)`

Wire shape from `docs/fleetq-relay-protocol.md`:

```json
client-relay.chunk:
{
  "request_id": "<uuid>",
  "chunk": "<text-delta>",
  "done": false,
  "usage": null
}

client-relay.error:
{
  "request_id": "<uuid>",
  "error": "<human-readable>"
}
```

Pusher client events triggered on the subscribed `private-daemon.<team_id>`
channel. Both raise `RuntimeError` if called before subscribe completes
(prevents silent drops on misconfigured startup).

### 2 · `chunk_handler` parameter

```python
def my_handler(payload: dict[str, Any]) -> Iterator[str]:
    for token in run_my_tool(payload):
        yield token

relay = BridgeRelay(
    base_url=..., api_token=..., team_id=..., app_key=..., relay_url=...,
    chunk_handler=my_handler,
)
```

When set:
- agent.request → handler → yielded text chunks → `client-relay.chunk` per token
- Final empty-chunk done=true sentinel closes the popChunk loop on the FleetQ side
- Handler exception → `client-relay.error`
- Missing `request_id` in payload → skip dispatch + WARNING (can't route reply)

### 3 · `_dispatch_chunk_handler()` failure isolation

Handler exceptions are caught and surfaced as `client-relay.error`
events. If the error publish ALSO fails (channel disconnected etc.),
the cleanup catches that too and logs at ERROR. The Pusher thread
never crashes; one buggy `agent.request` payload won't tear down the
relay.

### 4 · v1 log-only behaviour preserved

`chunk_handler=None` is the default. Without it, `_on_agent_request`
does what v1 did: parse the payload, log it at INFO, return. All 23
existing relay tests pass unmodified — pure additive change.

## Real numbers

- 1/1 previous-sprint retro action items shipped (item 1 — Bridge per-token streaming)
- 1 PR opened / merged (#21)
- 9 new unit tests in `test_relay.py`
- Test suite: 498 → 507 pass, 1 skip
- mypy --strict: 45 source files, clean
- ruff: clean
- Backwards-incompatible changes: 0 (`chunk_handler` defaults to None)
- Lines changed: +363 / -5

## What worked

- **Reading the wire-shape doc before writing code.** `docs/fleetq-relay-protocol.md`
  already had the JSON shape for both client events documented from
  v1.0.0a8's protocol spike. Implementing those exact dicts (rather
  than inventing my own) means the FleetQ side decodes correctly the
  first time it ships.

- **Capturing the channel object on subscribe.** v1's relay only
  needed the channel inside `_on_connection_established` — it bound
  handlers and dropped the reference. v2 needs to call
  `channel.trigger()` later, so I store `self._channel = channel`.
  Three lines of change unlocks the entire publish surface.

- **Pre-subscribe RuntimeError instead of silent skip.** The
  alternative ("if self._channel is None: return") would silently
  drop chunks during startup races. Loud failures surface bugs in
  caller code (e.g., dispatching before relay is ready) at the right
  layer.

- **Final empty-chunk done=true sentinel.** Even when the handler
  yields nothing, the relay still emits a `done=true` chunk so
  FleetQ-side popChunk doesn't hang. Three-line invariant; matches
  the protocol's "empty chunk closes stream" rule.

## What to change / next

- **Dispatcher layer not wired.** This phase ships the publish surface.
  Wiring `agent.request → MCP tool selection → ask_local_stream →
  chunk_handler iterator` is the next step. That's a thicker layer
  involving tool routing + permission checks; clean to defer to a v2.1
  phase if needed (or pull in for v2 GA).

- **No CI smoke for client events.** The `Live FleetQ Bridge smoke`
  job is gated on a repo secret and currently exercises register +
  heartbeat. Extending it to drive an `agent.request` → expect
  `client-relay.chunk` round trip would catch wire-shape regressions.

- **Pysher thread safety.** `_dispatch_chunk_handler` runs on
  Pusher's internal thread. If the handler is heavy (e.g., a real
  ask_local_stream subprocess), it blocks event delivery for that
  channel. A queue + worker thread is overkill for v2.0.0a7 but worth
  noting.

## Action items for the next sprint (v2.0.0 GA)

1. **Drop the alpha. Tag `v2.0.0`.** No new code — version bump,
   final retro, README status update. Mirror the v1.0.0 GA flow:
   the GA tag stamps the alpha arc as stable rather than introducing
   anything new.

## Out-of-scope (still)

- Tauri / Electron desktop UI wrapper — too big, no demand.
- Relay-binary path (Path B) — Path C HTTP tunnel covers the use case.
- agent.request → MCP dispatcher — the "wire whatever the operator
  configures into chunk_handler" story is enough for v2; full
  declarative dispatcher policy is v3 territory.
- Pusher worker-thread offloading — defer until somebody actually
  hits the issue.

# Sprint Retro — Harbormaster v1.0.0a8

**Date**: 2026-05-08
**Mode**: continuation of `/sprint-orchestrate full` ("продължи")
**Goal**: scaffold the Bridge reverse-channel — Pusher subscription, broadcasting-auth, event reception. Log-only this sprint; actual tool dispatch lands in v1.0.0a9.
**Outcome**: ✅ Tagged `v1.0.0a8`. 2 commits + ship. **203 tests pass + 1 intentional skip**. Second v1.1-track milestone landed.

---

## What landed

Two commits on `feat/harbormaster-v1.0.0a8`:

| SHA | Subject |
|-----|---------|
| `6a96b32` | feat(fleetq): BridgeRelay subscriber scaffolding (Pusher path, log-only) |
| (this commit) | ship: bump to 1.0.0a8 + sprint retro |

**Diff vs v1.0.0a7**: ~8 files changed, +1100 / −10.

---

## Capabilities (this sprint)

### 1 · Bridge reverse-channel subscriber (Pusher path, log-only)

Harbormaster now connects to FleetQ's Reverb server, authenticates the `private-daemon.<team_id>` channel via `/api/v1/bridge/broadcasting-auth`, subscribes, and **logs** every incoming `agent.request` event at INFO level. The actual MCP-tool dispatch + `client-relay.chunk` response routing lands in v1.0.0a9 — this sprint is the lifecycle and observability scaffolding.

Discovered protocol documented in [`docs/fleetq-relay-protocol.md`](fleetq-relay-protocol.md):

- `BridgeAgentRequest` event broadcasts on `PrivateChannel("daemon.{teamId}")` as `agent.request`. Payload is the bare dict from the dispatch site.
- `HandleBridgeRelayResponse` listener (in Reverb's process) consumes Pusher client events `client-relay.chunk` / `client-relay.error` and pushes chunks into Redis (`bridge:stream:{request_id}`) for the original `mcpCall` caller to `popChunk`.
- `broadcastingAuth` endpoint returns the standard Pusher auth signature `{"auth": "<app_key>:<hmac_hex>"}`.

### 2 · Auto-start on successful register

`__main__._maybe_start_fleetq_bridge` now returns a `_FleetQOrchestration` object pairing the heartbeat loop with the relay subscriber. On successful register (with a reverb block in the response), the relay is started. Stop sequence: relay.stop() (releases WS), then loop.stop() (deregisters from Bridge HTTP API). Best-effort: relay failure during start emits a warning but doesn't kill the registered bridge connection.

### 3 · Pluggable Pusher factory for testability

The `pysher.Pusher` constructor is wrapped in a `_default_pusher_factory` that's injectable via `BridgeRelay(pusher_factory=...)`. Tests use a `_FakePusher` fixture that captures `connection.bind` handlers and lets tests fire connection-established / agent.request events synchronously. Result: 23 fast deterministic tests that don't open real WebSockets.

---

## Real numbers

| Metric | v1.0.0a7 | v1.0.0a8 |
|--------|----------|----------|
| Source files | 25 | 26 (+ `fleetq/relay.py`) |
| Source LOC | ~1700 | ~2000 |
| Tests | 180 (179 + 1 skip) | 203 (202 + 1 skip) |
| `[fleetq]` deps | httpx | + pysher |
| MCP transports | 3 unchanged | 3 unchanged |
| `mypy --strict` / `ruff` | clean | clean (with pysher import-untyped override) |

---

## What worked

- **Discovery before code, again**. Reading `BridgeAgentRequest::broadcastOn/As/With` + `HandleBridgeRelayResponse::handleChunk/handleError` made the protocol concrete in 15 minutes. Without those reads I'd have invented event names that don't exist.
- **Inject the Pusher factory.** Decoupling `BridgeRelay` from a concrete `pysher` instance let the test suite stay fast and deterministic without a real WebSocket. This is the same pattern as the `subprocess.run` mock for backends but applied at a different boundary.
- **Log-only is a real shipping milestone.** Even without execution, the operator-visible log line ("BridgeRelay: agent.request received (request_id=req-123, method=tools/call) — execution dispatch lands in v1.0.0a9") is its own form of observability. If a user wires up a8, they can confirm the wire is alive before a9 lights up the engine.
- **`_FleetQOrchestration` paired stop semantics.** Relay first (releases WS), then heartbeat (deregisters). Single object handed to the `finally` block. No new global state.

## What to change / next

- **`agent.request` payload shape is inferred, not measured.** The Laravel event class accepts `array $payload` with no required keys. The MCP-tool-call dispatch site might not exist yet in agent-fleet (or may live in a class I haven't read). v1.0.0a9 must FIRST send a real `agent.request` from a test FleetQ instance and capture the actual payload before designing the dispatcher.
- **No reconnect logic.** If the Reverb connection drops, pysher's internal reconnect kicks in but our `BridgeRelay` doesn't re-subscribe with a fresh `socket_id`. Bind a `pusher:connection_established` handler that's idempotent and re-fetches auth on every connection-established event (already partially done — verify it actually re-subscribes).
- **No client-relay.error path tested.** When dispatch fails (in v1.0.0a9), we'll need to send `client-relay.error` events. The Pusher `client-*` event prefix has special semantics (must be enabled per channel). Verify Reverb allows this on private channels for the daemon principal.
- **BridgeRelay does not appear in `/api/health` or `/api/projects`.** Ops can't easily ask "is the relay subscribed?" via HTTP. Consider exposing `relay.subscribed` and `relay.socket_id` via a new `/api/bridge/status` route (or extending `/api/health`).

---

## Action items for the next sprint (v1.0.0a9 / week 9)

1. **Capture a real `agent.request` payload** from an actual FleetQ test instance. Spike. Document the exact shape.
2. **Implement dispatch**: when `agent.request` arrives, look up the requested MCP tool in `mcp._tool_manager`, execute it (sync — these are fast tools), serialize the result, send `client-relay.chunk` with `done=true`.
3. **Map errors to `client-relay.error`** with `request_id` + `error` fields.
4. **Add `relay.subscribed` to `/api/health`** so ops can monitor.
5. **Reconnect / re-subscribe on Reverb disconnect.** Verify pysher's reconnect triggers our `_on_connection_established` again with a fresh socket_id and we redo the auth.
6. **Live integration test** against a real FleetQ instance (gated, optional) — the only way to validate the full circuit.

## Out-of-scope (still)

- Q&A history / federated KG / auto project graph — v1.2 roadmap.
- Backends other than Claude — wait for first user request.
- Plugin / extensions API — v2.
- Tauri / Electron native UI wrapper — post-v1.2.
- Streaming responses (multiple `client-relay.chunk` with `done=false`) — defer to v1.0.0a10+ once single-chunk dispatch is solid.

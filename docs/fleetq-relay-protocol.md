# FleetQ Bridge Relay Protocol — Pusher path

**Source**: `agent-fleet/base/app/Infrastructure/Bridge/{Events/BridgeAgentRequest.php,HandleBridgeRelayResponse.php,BridgeRequestRegistry.php}` + `Http/Controllers/Api/V1/BridgeController.php::broadcastingAuth` (read 2026-05-08).

**Scope**: this is the contract Harbormaster v1.0.0a8 starts subscribing against. v1.0.0a8 ships **subscriber scaffolding only** — connect, authenticate, subscribe, log received events. The actual MCP-tool dispatch + response routing lands in v1.0.0a9.

There is also a parallel **relay-binary path** (`bridge:req:{teamId}` Redis list, frame-based binary protocol on a custom WebSocket) used by `BridgeController::mcpCall`. That path is **out of scope** indefinitely — implementing it requires a separate Go-style frame decoder and is what FleetQ's first-party bridge daemon does. Harbormaster's strategy is the simpler Pusher-only path.

---

## Connection

The daemon connects to Reverb (Laravel's Pusher-protocol server). Connection details come from the register response:

```json
{
  "reverb": {
    "app_key": "<reverb_app_key>",
    "relay_url": "wss://app.fleetq.net:443"
  }
}
```

Reverb implements the standard Pusher protocol. Any Pusher-compatible client (e.g. `pysher`) can connect with `app_key`, `host`, `port`, `secure=true`. Cluster is irrelevant for self-hosted Reverb.

---

## Authentication

Private channels (`private-*`) require a signed auth token. Pusher's signing scheme is HMAC-SHA256 over `socket_id:channel_name`, but FleetQ exposes a server-side helper at:

```
POST /api/v1/bridge/broadcasting-auth
Authorization: Bearer <sanctum_token>
Content-Type: application/x-www-form-urlencoded   ; or JSON

socket_id=<connection-socket-id>
channel_name=private-daemon.<team_id>
```

**Response 200**:
```json
{ "auth": "<reverb_app_key>:<hex_hmac_sha256>" }
```

**Response 403**: channel name doesn't match the team the Sanctum token resolves to (or unsupported channel pattern).

The daemon uses the response's `auth` field as the `auth` parameter when subscribing (Pusher protocol's `pusher:subscribe` event).

Pysher accepts a custom `auth_endpoint` URL with custom headers — point it at `<base_url>/api/v1/bridge/broadcasting-auth` and pass `Authorization: Bearer <token>`.

---

## Subscription

```
Channel:           private-daemon.<team_id>
Event to listen:   agent.request
Event payload:     varies — passed through from BridgeAgentRequest::__construct($teamId, $payload)
```

The Laravel event class (`App\Infrastructure\Bridge\Events\BridgeAgentRequest`) wraps an arbitrary `array $payload` and broadcasts it on `private-daemon.{teamId}` as `agent.request`.

The payload shape depends on what FleetQ-side code dispatched the event. For MCP tool calls, expect at minimum:

```json
{
  "request_id": "<uuid>",
  "server": "harbormaster",
  "method": "tools/call",          // or "tools/list"
  "params": { "name": "...", "arguments": {...} },
  "timeout": 60
}
```

(This is inferred from `BridgeController::mcpCall`'s frame payload — the Reverb-path event likely mirrors it.)

---

## Daemon → FleetQ response

The daemon replies via Pusher **client events** on the same channel. Reverb's `MessageReceived` event handler (`HandleBridgeRelayResponse`) intercepts them and pushes the chunks into Redis (`bridge:stream:{request_id}`), where the original waiting request (`BridgeController::mcpCall::popChunk`) eventually picks them up.

Two accepted client events:

### `client-relay.chunk`

```json
{
  "request_id": "<same-uuid>",
  "chunk": "<json-encoded-mcp-result-string>",
  "done": true,
  "usage": null
}
```

`done: true` signals end of stream. Streaming responses can send multiple chunks with `done: false` and a final `done: true`.

`usage` (optional, sent on the final chunk) is `{prompt_tokens: int, completion_tokens: int}` for LLM-style requests; not relevant for MCP tool calls.

### `client-relay.error`

```json
{
  "request_id": "<same-uuid>",
  "error": "<human-readable error>"
}
```

Triggers the FleetQ side to wake `popChunk` with a sentinel and re-throw the error to the original mcpCall caller.

---

## Pusher protocol envelope (received)

Pusher sends events to subscribers as one outer JSON message:

```json
{
  "event": "agent.request",
  "channel": "private-daemon.<team_id>",
  "data": "<json-encoded-string-of-the-payload>"
}
```

Note: `data` is a JSON-encoded **string**, not a nested object. Standard Pusher quirk — any subscriber must `json.loads(message["data"])` to get the payload dict.

---

## Pusher protocol envelope (sent — client events)

Client events go OUT as:

```json
{
  "event": "client-relay.chunk",
  "channel": "private-daemon.<team_id>",
  "data": { ... }
}
```

`data` here can be a dict (Pysher serializes it for you) or a JSON-encoded string. The Reverb `HandleBridgeRelayResponse` listener handles both.

---

## What v1.0.0a8 ships

- New module `harbormaster.fleetq.relay` with class `BridgeRelay`.
- Connection lifecycle: connect → authenticate via `/api/v1/bridge/broadcasting-auth` → subscribe to `private-daemon.{team_id}` → log received `agent.request` events at INFO level.
- Wired into `HeartbeatLoop`: started after the first successful `register()`, stopped on `disconnect()`.
- `pysher>=1.0` added to the `[fleetq]` extra.
- Tests via mocked Pusher client.

## What v1.0.0a9+ ships

- Decode the `agent.request` payload, look up the requested MCP tool in `FastMCP._tool_manager`, invoke it via Python (since we own the tool registry in-process).
- Serialize the MCP result, send `client-relay.chunk` with `done=true`.
- Map exceptions to `client-relay.error`.
- Streaming responses (multiple chunks) for tools that produce incremental output.
- Live integration test against a real FleetQ instance.

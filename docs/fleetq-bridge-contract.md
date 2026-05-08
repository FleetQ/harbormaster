# FleetQ Bridge — Discovered Contract

**Source**: `agent-fleet/base/app/Http/Controllers/Api/V1/BridgeController.php`, the matching `Domain/Bridge/Actions/*` and `Domain/Bridge/Models/BridgeConnection.php` (read 2026-05-08 against `agent-fleet` v0.x).

**Scope**: this is the contract Harbormaster v1.0.0a6 implements. The reverse-WebSocket relay channel (Reverb / Pusher private channels for MCP proxy) is **out of scope** for v1.0.0a6 — it's its own substantial chunk of work, deferred to v1.0.0a7+.

---

## Auth

All Bridge endpoints sit under `/api/v1/bridge/*` and use Laravel **Sanctum bearer tokens**. The token must have a `team:<team_uuid>` ability (preferred) — the controller's `resolveTeamId()` reads abilities first, then falls back to the user's `current_team_id`.

```
Authorization: Bearer <sanctum_token>
Content-Type: application/json
Accept: application/json
```

---

## Endpoints

### `POST /api/v1/bridge/register`

Called by the bridge daemon on first connect (and on reconnect — the action upserts).

**Request**:
```json
{
  "session_id": "harbormaster-<uuid7>-<unix_ts>",
  "bridge_version": "1.0.0a6",
  "label": "harbormaster on jarvis.local",
  "endpoints": {
    "agents": [],
    "llm_endpoints": [],
    "mcp_servers": [
      {
        "name": "harbormaster",
        "description": "Project-router MCP — list/status/ask/delegate/fan_out/list_hosts",
        "tools": ["list_projects", "list_hosts", "project_status",
                  "ask_project", "delegate_task", "fan_out_ask"]
      }
    ]
  }
}
```

- `session_id` — required, ≤255 chars. Convention: `<bridge>-<uuid7>-<unix_ts>` so stale sessions self-expire visually.
- `bridge_version` — optional, ≤50 chars. We send `harbormaster.__version__`.
- `label` — optional, ≤100 chars. Free-form display string.
- `endpoints` — optional dict with `agents`, `llm_endpoints`, `mcp_servers` keys (all arrays). v1.0.0a6 announces only `mcp_servers`.

**Response 201**:
```json
{
  "data": {
    "session_id": "harbormaster-...",
    "team_id": "<uuid>",
    "connected_at": "2026-05-08T12:34:56.000000Z",
    "reverb": {
      "app_key": "<reverb_app_key>",
      "relay_url": "wss://app.fleetq.net:443"
    }
  }
}
```

The `reverb` block is the WebSocket relay info for the bidirectional MCP proxy — **v1.0.0a6 ignores it**. Future sprints will use `pusher.private(daemon.<team_id>)` to receive incoming MCP tool calls.

### `POST /api/v1/bridge/heartbeat`

Called periodically by the daemon to keep `last_seen_at` fresh and re-activate any connection that `detect-stale` marked as `Disconnected`.

**Request**:
```json
{ "session_id": "harbormaster-..." }
```

**Response 200**: `{"data": {"alive": true}}`
**Response 404**: `{"error": "Session not found."}` — recovery path: re-call `register` to upsert.

### `POST /api/v1/bridge/endpoints`

Called whenever the daemon's local discovery changes (e.g. user adds a new MCP server). v1.0.0a6 doesn't dynamically rediscover, so we only call this once on register if needed.

**Request**:
```json
{
  "session_id": "harbormaster-...",
  "endpoints": { "mcp_servers": [...] }
}
```

**Response 200**: `{"data": {"updated": true}}`

If `session_id` is missing, the controller falls back to the most recent active connection for the team. If no connection exists at all, the endpoints get cached in Redis (`bridge:pending_endpoints:<team>`) for 60s — when `register` is called next, the cached endpoints are picked up.

### `DELETE /api/v1/bridge/`

Disconnects. The Bridge then transitions the connection's status to `Disconnected`.

**Request**:
```json
{ "session_id": "harbormaster-..." }
```

(Without `session_id`, disconnects ALL active connections for the team — we always send the session_id.)

**Response 200**: `{"data": {"disconnected": 1}}` (or `0` if our session was already superseded — the controller's "stale disconnect ignored" path).

### `GET /api/v1/bridge/status`

Read-only, returns all connections for the team. Useful for debugging — Harbormaster doesn't depend on this.

---

## Status enum

```
connected
disconnected
reconnecting
```

`detect-stale` (Bridge background job, exact frequency not relevant to client) marks connections as `Disconnected` after a heartbeat gap. Harbormaster recovers via 404 on heartbeat → re-register.

---

## What lives where in `agent-fleet`

| File | What it owns |
|------|--------------|
| `app/Http/Controllers/Api/V1/BridgeController.php` | The 7 endpoints documented above plus `mcpCall`, `connect`, `updateUrl`, `ping`, `broadcastingAuth` (HTTP-tunnel + Reverb auth — out of scope for v1.0.0a6) |
| `app/Domain/Bridge/Actions/RegisterBridgeConnection.php` | Upsert logic — re-uses existing connection by session, then by latest, or creates new |
| `app/Domain/Bridge/Actions/UpdateBridgeEndpoints.php` | Trivial endpoints update + last_seen_at touch |
| `app/Domain/Bridge/Actions/TerminateBridgeConnection.php` | Sets status=disconnected, disconnected_at=now |
| `app/Domain/Bridge/Models/BridgeConnection.php` | Eloquent model, `BelongsToTeam`, casts `endpoints` to array |
| `app/Domain/Bridge/Enums/BridgeConnectionStatus.php` | The 3-value enum |

---

## Out of scope for v1.0.0a6

- **Reverb / Pusher reverse channel** — the daemon is supposed to subscribe to `private-daemon.<team_id>` and respond to incoming MCP tool calls via the channel. Without it, Harbormaster shows up in FleetQ's UI as "connected" but every `mcpCall` from FleetQ to harbormaster will return 404 "no active bridge with MCP server harbormaster".
- **HTTP-tunnel mode** (`POST /api/v1/bridge/connect` with `endpoint_url`) — alternative to the WebSocket relay, the user pastes a Cloudflare/ngrok URL. Easier to implement but requires the user to set up a public tunnel. Defer to v1.0.0a7+ alongside reverse-channel.
- **Discovery of other local MCP servers / LLM endpoints / agents.** Harbormaster announces only itself. The richer "discover all local MCPs and proxy them" behavior is what the official FleetQ Bridge daemon does.

This contract gets us to "registered + heartbeating", which is enough to validate the integration end-to-end against a real FleetQ instance and ship the wire format. Reverse channel comes after we have one user actually running the integration.

# Spike: real `agent.request` payload from local FleetQ

**Date**: 2026-05-08
**Setup**: agent-fleet stack on `nginx.agent-fleet.orb.local` (Docker / OrbStack), Sanctum token created via direct DB insert (Passport boot was failing in the container, blocking `User::createToken()`).

## TL;DR — protocol mismatch with harbormaster's actual use case

**The Pusher / Reverb `agent.request` event channel is for LLM and bridge-agent (CLI) inference, NOT for MCP tool calls.**

MCP tool calls (`/api/v1/bridge/mcp-call` controller method) push frames into a Redis list (`bridge:req:{teamId}`) which are consumed by a separate **relay binary** (Go/Rust binary, separate from FleetQ itself) that maintains custom-protocol WebSocket connections to bridge daemons. Frame protocol uses `frame_type` constants — `0x0020 FrameMcpToolCall`, `0x0021 FrameMcpToolResult`, etc. (see `BridgeRequestRegistry::popChunk` docblock for the full table).

The Reverb path was added as an alternative for daemons that connect via `php artisan bridge:start` style and don't have the relay binary in front of them — but only for **LLM / agent** inference (`bridge_llm` / `bridge_agent` providers in `LocalBridgeGateway`). MCP calls always go through the relay-binary path.

## Evidence

### Where `BridgeAgentRequest` is dispatched

```
agent-fleet/base/app/Infrastructure/AI/Gateways/LocalBridgeGateway.php:199
    broadcast(new BridgeAgentRequest($request->teamId, $payload['payload'] ?? $payload));
```

The only call site. `LocalBridgeGateway` is the `AiGateway` for providers `bridge_llm` and `bridge_agent` — both LLM-inference workloads. There is **no** MCP-related code path that broadcasts `BridgeAgentRequest`.

### Where MCP tool calls actually flow

```
agent-fleet/base/app/Http/Controllers/Api/V1/BridgeController.php:296-375  (mcpCall)
```

Pushes JSON frame `{request_id, frame_type: 0x0020, payload: {...}}` to `bridge:req:{teamId}` Redis list. Reads response chunks via `BridgeRequestRegistry::popChunk` from `bridge:stream:{request_id}`. No Reverb broadcast.

### What the Pusher event actually carries

Two payload shapes (from `LocalBridgeGateway::buildPayload`):

**`bridge_agent` (frame 0x0010)**:
```json
{
  "request_id": "<uuid>",
  "agent_key": "claude-code",
  "model": "claude-sonnet-4-5",
  "prompt": "<user prompt>",
  "system_prompt": "<system>",
  "purpose": "<purpose>",
  "stream": true,
  "env": { "CRED_*": "..." }
}
```

**`bridge_llm` (frame 0x0001)**:
```json
{
  "request_id": "<uuid>",
  "endpoint_url": "...",
  "model": "...",
  "messages": [{"role":"system|user","content":"..."}],
  "max_tokens": 8192,
  "temperature": 0.7,
  "stream": true
}
```

Note that `BridgeAgentRequest` ctor receives `$payload['payload'] ?? $payload`. With the `buildPayload` outputs above, the daemon receives the inner payload dict (not the outer envelope with `frame_type`).

---

## What this means for harbormaster

### What v1.0.0a8 BridgeRelay actually unlocks

Harbormaster's `BridgeRelay` subscriber will receive **LLM / bridge-agent inference requests** when a FleetQ user configures a provider of type `bridge_llm` or `bridge_agent` and routes a request through `LocalBridgeGateway`. Harbormaster could in principle dispatch these to local LLMs (via PrismPHP-style provider) or local CLI agents (claude / codex) — but that's not what harbormaster is for. Harbormaster's tools are **MCP tools** (project routing).

### What it does NOT unlock

MCP tool routing from FleetQ → harbormaster does **not** flow over the Pusher channel. It goes through Redis+relay-binary. No matter how completely we implement Pusher subscription + dispatch, FleetQ users calling `harbormaster::list_projects` from a FleetQ agent will continue to hit "no active bridge with MCP server harbormaster" because the relay binary isn't there to forward the frame.

### Three paths forward

**A. Acknowledge the limitation and ship as-is**
- Harbormaster registers as a bridge (visibility ✅), exposes /discover for HTTP-tunnel registration UI flow ✅, has Pusher subscription scaffolding ✅. But MCP tool routing FleetQ → harbormaster doesn't work today.
- v1.0 GA is feasible. Document the limitation in README.
- Strategically: harbormaster's value is mostly as a stand-alone MCP server for Claude Code / Desktop. The FleetQ integration is gravy.

**B. Implement the relay-binary protocol**
- Custom WebSocket. Frame-based binary protocol with `uint16 frame_type, []byte payload, bool done`.
- Need to find / read the relay binary source — it's a separate Go (or Rust?) project not in `agent-fleet`. May not be open source.
- Multi-sprint effort. Possibly multi-week.

**C. Upstream a PR to agent-fleet adding HTTP-direct MCP routing**
- Modify `BridgeController::mcpCall` to dispatch differently when the resolved BridgeConnection is in HTTP-mode (`endpoint_url` is set).
- POST to `<endpoint_url>/mcp/<server>/call` with the same payload shape, parse the synchronous response.
- Coordinated work — but unblocks harbormaster and other future HTTP-tunnel-mode bridges (Cloudflare Tunnel daemons, Tailscale Funnel daemons, etc.). Aligns with FleetQ's existing HTTP-tunnel investments.
- Estimated: 1 PR to agent-fleet (~50 lines + tests), 1 sprint of harbormaster work to add the receiving endpoint and tests.

## Recommendation

**Path C** is the most leverageable: small change to FleetQ, then harbormaster's MCP tools become routable from FleetQ agents over a clean HTTP boundary. No relay binary to maintain. No custom WebSocket protocol to implement.

If C is not in the cards, **Path A** is the honest stop point — ship harbormaster v1.0 as a strong stand-alone MCP server with optional FleetQ visibility. Don't promise routing that doesn't work.

## Live verification (2026-05-08, after Path C ship)

After landing harbormaster's `POST /mcp/{server}` endpoint and the
agent-fleet `feat/mcp-call-http-direct` branch (PR
https://github.com/escapeboy/agent-fleet-o/pull/72), the full chain
was tested against the local OrbStack FleetQ:

```
FleetQ user → POST /api/v1/bridge/mcp/call (Sanctum bearer)
    → BridgeController::mcpCall
    → resolveForMcpServer returns the HTTP-tunnel-mode connection
    → mcpCallViaHttp POSTs to host.docker.internal:7531/mcp/harbormaster
    → harbormaster-ui's /mcp/{server} endpoint dispatches to FastMCP
    → tool result wrapped in MCP envelope, returned synchronously
    → 200 reaches the original FleetQ caller
```

Verified payloads (via `/Users/katsarov/htdocs/harbormaster/.venv/bin/python`):

- `tools/list` → 200, returned all 6 tools (`list_projects`,
  `list_hosts`, `project_status`, `ask_project`, `delegate_task`,
  `fan_out_ask`).
- `tools/call name=list_hosts` → 200, real SSH hosts:
  `github.com, pricex, lukanet, ghcr.io, auth.lukanet.com,
  sandbox.barsy.in, friday, sage-production`.
- `tools/call name=i_do_not_exist` → 502 wrapping daemon's 404
  with body `{"detail":"tool not found: 'i_do_not_exist'"}`.

End-to-end MCP routing FleetQ ↔ harbormaster is now functional
without a relay binary. Path C delivered.

## Spike artefacts

- Token created via direct DB insert (Passport boot in container blocks `User::createToken()`):
  ```php
  DB::table('personal_access_tokens')->insert([...]);
  ```
- `/api/v1/bridge/status` returns 200 with `{connected: false, connections: []}` — no harbormaster registered yet.
- agent-fleet stack runs:
    - app + horizon + scheduler + nginx (8088)
    - reverb (8080) — Pusher-protocol server
    - postgres (5433) + redis (6380)
- `.env` reveals: `REVERB_APP_KEY=qaeouhqrig8tfmrwazk1`, `REVERB_HOST=localhost`, `REVERB_PORT=8080`.

# Sprint Retro — Harbormaster v1.0.0a9

**Date**: 2026-05-08
**Mode**: continuation of `/sprint-orchestrate full` ("продължи")
**Goal**: capture a real `agent.request` payload, design dispatcher around it, ship the end-to-end FleetQ ↔ harbormaster MCP path.
**Outcome**: ✅ Tagged `v1.0.0a9`. **Architectural pivot mid-sprint** + **end-to-end working** against local OrbStack FleetQ. 212 tests pass + 1 intentional skip on harbormaster side; 4 new feature tests on the agent-fleet PR (15 total in BridgeControllerTest).

---

## What landed

Two repositories, one shipped feature:

### `harbormaster` (this repo)

| SHA | Subject |
|-----|---------|
| `7bbbd4c` | feat(ui): POST /mcp/{server} HTTP-direct routing endpoint (Path C) |
| (this commit) | ship: bump to 1.0.0a9 + sprint retro |

### `agent-fleet` (community-edition base submodule)

| SHA | Subject |
|-----|---------|
| `3f446842` | feat(bridge): HTTP-direct MCP routing for HTTP-tunnel-mode bridges |

PR opened on `agent-fleet-o#72` against `develop`. Draft / awaiting review.

---

## Mid-sprint pivot (the real story)

The sprint started with the assumption that `BridgeAgentRequest` events broadcast on `private-daemon.{teamId}` would carry MCP tool calls. The spike disproved this:

- `BridgeAgentRequest` is dispatched **only** from `LocalBridgeGateway::routeRequest` (single call site), and only for `bridge_llm` / `bridge_agent` providers — i.e. LLM and CLI-agent inference, **not** MCP tool calls.
- MCP tool calls (`BridgeController::mcpCall`) flow through Redis (`bridge:req:{teamId}`) and a separate Go/Rust **relay binary** that talks to bridge daemons over a custom WebSocket frame protocol (`frame_type 0x0020 FrameMcpToolCall`, etc.).

Three paths forward (in [`docs/agent-request-payload-spike.md`](agent-request-payload-spike.md)):

- **A. Acknowledge limitation** — ship harbormaster v1.0 as a strong stand-alone MCP server with FleetQ visibility but no MCP routing.
- **B. Implement relay-binary protocol** — multi-week effort, separate Go/Rust source needed.
- **C. Upstream PR to agent-fleet adding HTTP-direct MCP routing** — small, leverageable, ships harbormaster's MCP tools without a relay.

User chose **Path C**. The rest of the sprint executed it.

---

## Capabilities (this sprint)

### 1 · `POST /mcp/{server}` on harbormaster's UI app

Body shape mirrors agent-fleet's `BridgeController::mcpCall` validate() block: `{request_id?, method, params, timeout?}`. Methods are `tools/call` or `tools/list` (regex-validated by pydantic). Routes look up the tool in FastMCP's registry, invoke it, wrap the result in MCP JSON-RPC envelope shape `{result: {content: [{type:"text", text:...}]}}`. Tool exceptions return `isError: True` instead of 500.

`create_app(config, *, mcp=None)` — new optional `mcp` kwarg threads a FastMCP instance through routes; without it the endpoint 404s with a helpful detail. `harbormaster-ui` CLI now constructs the MCP server alongside the UI so a single process owns both.

### 2 · agent-fleet PR — HTTP-direct routing

`BridgeController::mcpCall` now branches: when the resolved `BridgeConnection` is HTTP-tunnel-mode (`endpoint_url` set), it POSTs directly to `{endpoint_url}/mcp/{server}` instead of pushing to the Redis+relay path. Same body shape, daemons can share handler logic across transports. Failure modes mapped to 502 with informative messages.

### 3 · End-to-end live verification

Against the local OrbStack FleetQ instance:

```
FleetQ /api/v1/bridge/mcp/call (Sanctum)
  → BridgeController::mcpCall
  → mcpCallViaHttp POST host.docker.internal:7531/mcp/harbormaster (Bearer endpoint_secret)
  → harbormaster-ui /mcp/{server} → FastMCP._tool_manager → tool.fn(**args)
  → MCP envelope back through 4 hops → caller
```

Verified payloads:

- `tools/list` → 6 tools enumerated.
- `tools/call name=list_hosts` → real SSH hosts: `github.com, pricex, lukanet, ghcr.io, auth.lukanet.com, sandbox.barsy.in, friday, sage-production`.
- `tools/call name=i_do_not_exist` → 502 wrapping daemon's 404.

Documented in the spike doc.

---

## Real numbers

| Metric | v1.0.0a8 | v1.0.0a9 |
|--------|----------|----------|
| Source files | 26 | 26 (no new modules; routes.py + cli.py + app.py extended) |
| Source LOC | ~2000 | ~2200 |
| Tests (harbormaster) | 203 (202 + 1 skip) | 213 (212 + 1 skip) |
| Tests (agent-fleet BridgeControllerTest) | 11 | 15 |
| MCP routing FleetQ ↔ harbormaster | ❌ | ✅ |
| `mypy --strict` / `ruff` | clean | clean |

---

## What worked

- **Spike-first.** 30 minutes of reading `LocalBridgeGateway`, `BridgeAgentRequest`, `HandleBridgeRelayResponse`, and `BridgeRequestRegistry` saved a multi-week dead-end implementing the wrong protocol. Without the spike, v1.0.0a9 would have built a Pusher-side dispatcher that never receives MCP calls.
- **Honest pivot when the discovery contradicted the plan.** I asked the user with three concrete options instead of silently picking one. Path C was the right call.
- **Two-repo coordinated change.** harbormaster's receive endpoint shipped first (independently testable), agent-fleet's PR is the unlock. The PR can land on its own schedule; harbormaster doesn't break in the interim.
- **Live integration before retro.** Restarting the agent-fleet app container revealed PHP-FPM was holding the old `BridgeController` class in memory despite OPcache being disabled. Without the restart we'd have shipped thinking integration worked when it didn't. Worth a permanent note: "after editing controllers in dev Docker, `docker compose restart app`".

## What to change / next

- **agent-fleet PR is on `escapeboy/agent-fleet-o`**, not a public FleetQ org. The harbormaster public release talks about "FleetQ" but the actual PR lives in escapeboy's mono. If the user wants a true OSS story, either move agent-fleet to a `FleetQ/` org or update harbormaster's docs to point at the actual repo.
- **Error mapping is asymmetric.** harbormaster's `/mcp/{server}` returns 404 for unknown tools; agent-fleet's `mcpCallViaHttp` wraps that as 502. From the FleetQ caller's perspective, "tool not found" looks like a generic gateway error. Future polish: pass through 4xx daemon responses as-is (not always 502).
- **No streaming yet.** v1.0.0a9 ships synchronous request/response only. Tools that produce incremental output (e.g. `ask_project` which streams claude tokens) would benefit from chunked responses; would require either SSE or chunked transfer encoding on both sides.
- **No `update_endpoints` after register.** The bridge's manifest is static. If the user adds a project at runtime, FleetQ doesn't see it. Carry-over from a6 retro.
- **Live integration is manual.** Worth scripting as a CI smoke job — gated by FLEETQ_TEST_BASE_URL env var, only runs when the user's local FleetQ is reachable.

---

## Action items for the next sprint (v1.0.0a10 / week 10)

1. **PyPI publish v1.0.0a9** — actually flip the switch on the publish workflow. The PR + harbormaster integration are now usable; users can install.
2. **Streaming `tools/call` responses** — chunked transfer / SSE per-tool. Important for `ask_project` / `delegate_task` / `fan_out_ask` which take 30s+.
3. **Carry-over: `update_endpoints` config-watch loop** (from a6).
4. **Live FleetQ integration as CI smoke** (gated).
5. **agent-fleet PR review + merge** — coordinate with the user's review cycle.
6. **Polish error mapping** between agent-fleet and harbormaster (pass through 4xx instead of always wrapping as 502).

## Out-of-scope (still)

- Q&A history / federated KG / auto project graph — v1.2 roadmap.
- Backends other than Claude — wait for first user request.
- Plugin / extensions API — v2.
- Tauri / Electron native UI wrapper — post-v1.2.
- Relay-binary path (Path B) — explicitly skipped in favour of Path C.

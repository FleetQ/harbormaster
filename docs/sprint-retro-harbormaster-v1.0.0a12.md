# Sprint Retro — Harbormaster v1.0.0a12

**Date:** 2026-05-09
**Theme:** Closed the streaming loop. v1.0.0a10 added the daemon-side
SSE wire shape, a11 wired the FleetQ Bridge consumer + landed the
stream-json parser, and a12 brings them together — `ask_project` over
the local backend now emits real per-token `chunk` events on the wire.
The user-visible UX shifts from "30s of silence then the answer" to
"watch the model think." Plus a CI wire-shape smoke that catches
regressions every push.

## What landed

### `harbormaster` (this repo)

| SHA | Subject |
|-----|---------|
| `329f34a` | feat(ui): wire ask_local_stream into SSE dispatch with chunk events (#6) |

## Capabilities (this sprint)

### 1 · Per-token chunk streaming for `ask_project` (local)

When `Accept: text/event-stream` + `tools/call` + `params.name ==
"ask_project"` + `host` is `None` or `"local"`, the dispatcher now
bypasses FastMCP's sync tool registry and drives
`ClaudeBackend.ask_local_stream` directly. Each yielded text delta
becomes one `chunk` SSE event:

```
event: chunk        ← one per assistant text delta from --output-format stream-json
data:  {"text": "Hello, "}

event: chunk
data:  {"text": "world."}

event: result       ← final envelope (MCP-shaped, identical to JSON mode)
data:  {"result": {"content": [{"type": "text", "text": "Hello, world."}]}}
```

Failure modes route through in-band SSE error events so callers
never face a mid-flight transport switch:

| Trigger | event | status |
|---|---|---|
| missing/empty `name` or `question` | `error` | 400 |
| unknown project (`resolve_project` ValueError) | `error` | 400 / 502 |
| `BackendError` raised mid-iteration (timeout / exit_nonzero / parse_failure) | `error` | 502 |

JSON mode (no `Accept: text/event-stream`, no `params.stream`) is
bit-identical to v1.0.0a11. The non-`ask_project` SSE branch (and
`ask_project` over SSH) falls through to the existing heartbeat +
result path unchanged.

### 2 · `smoke-mcp-streaming` CI job

New CI job spins up `harbormaster-ui` (which auto-binds the MCP
server), POSTs `tools/list` with `Accept: text/event-stream` + bearer
token, and asserts:

- `Content-Type: text/event-stream`
- response body contains `event: result`
- response body lists `ask_project` in the tool registry

Doesn't need a real `claude` binary — `tools/list` returns the static
registry so the test is fast and deterministic. The `build` job's
`needs:` array now includes `smoke-mcp-streaming`, so a wire-shape
regression blocks publishing.

### 3 · README "Streaming" section

New "Streaming" section between Tools and v1 limits, with a curl
example for direct callers and a one-liner explaining the FleetQ
Bridge `stream: true` flag. v1 limits gained an explicit "per-token
chunk events are local-only" line so callers know SSH still falls
back to heartbeat + final result.

## Real numbers

- 3/6 v1.0.0a11 retro action items shipped (items 1, 2, 3)
- 1 PR opened, 1 merged
- 5 new async unit tests for `_stream_ask_project_local`
- Test suite delta: 228 → 233 passed on harbormaster (1 skipped)
- Lint clean (ruff), mypy --strict clean across 26 source files
- 0 backward-incompatible changes

## What worked

- **Async direct-iteration tests over TestClient.stream().** Switching
  from `client.stream(...)` to `async for evt in
  _stream_ask_project_local(...)` made the chunk tests deterministic
  AND fast (33ms total). TestClient under SSE waits for EOF that
  sse-starlette doesn't reliably send — caught after a 5-minute hang
  on the first attempt. Direct iteration tests the same code path
  the route handler wraps; the route handler itself is one
  `EventSourceResponse(...)` call exercised by the existing heartbeat
  tests.
- **Documenting the asyncio gotcha in code AND in PR body.** PEP 479
  / "StopIteration interacts badly with generators and cannot be
  raised into a Future" cost an hour of debugging. Captured in the
  source comment on `_next_or_sentinel` and called out in the PR body
  so the next person who sees `asyncio.to_thread(next, gen)` knows
  why the wrapper exists.
- **CI wire-shape smoke without a Claude binary.** Reusing
  `tools/list` for the live test means no fake-claude shim, no
  network secret, no flakiness. The smoke is more reliable than a
  fake-claude integration test would have been, and it runs in 17s.
- **Sprint retro template paid off again.** Second consecutive retro
  written from the template; the structure shows up in PR bodies
  (`Wire shape`, `Routing decision`, `Failure modes`) which makes
  reviewers' lives easier.

## What to change / next

- **The chunk path is silent on `delegate_task` and `fan_out_ask`.**
  Both are similarly long-running but only `ask_project` got the
  streaming hookup. Either widen the bypass to all three or document
  the gap clearly in the README. Keeping it ask_project-only for
  now is defensible (it's the most common call), but unguarded silence
  on the other two is a small UX trap.
- **No live end-to-end smoke through FleetQ.** The new
  `smoke-mcp-streaming` hits harbormaster directly. We still don't
  have a CI job that exercises `FleetQ caller → Bridge → harbormaster`
  with `stream=true`. The gated `smoke-fleetq` could be extended,
  but it's harder to write a useful timing-based assertion when the
  network hop variance dominates.
- **resolve_project ValueError surfaces as 502 sometimes, 400
  others.** It depends on whether the call hits inside the generator
  body or the construction step (the generator body always wins, so
  it's effectively always 502 today). The unit tests accept either,
  which means the contract is fuzzier than it could be. Worth
  tightening: validate the project name BEFORE constructing the
  iterator so we get a deterministic 400.
- **`tools/_helpers.stream_ask_project_local` is named for the tool,
  not the operation.** When `delegate_task` gets the same treatment,
  we'll have `stream_delegate_task_local`, etc. Better factor it as
  `stream_local_backend(tool_name, prompt_builder, ...)` once we
  have the second caller.

## Action items for the next sprint (v1.0.0a13 / week 13)

1. **`ask_remote_stream` (SSH variant).** Pipe `claude -p
   --output-format stream-json` through `ssh` so SSE chunks work
   against remote projects. Carries forward the v1.0.0a11 retro
   item #6. Needs careful stdout demux because ssh's own status
   messages can interleave with claude's lines.
2. **Widen chunk streaming to `delegate_task` + `fan_out_ask`.**
   Same pattern as a12 #1 but for the other two long-running
   tools. Refactor `stream_ask_project_local` →
   `stream_local_backend(tool, prompt_builder)` while at it.
3. **Tighten `resolve_project` validation.** Move the project-name
   resolution out of the generator body so the caller gets a
   deterministic 400, not maybe-400-maybe-502.
4. **Begin v1.1 scope.** Start the FleetQ Platform Tool seeder PR
   in agent-fleet (registers Harbormaster as `McpStdio`,
   `risk_level=Read`). Carry-over from a10 retro #4 → a11 #5 → a12.
   This sprint is the right time — streaming is closed, polish is
   thin, and v1.1 is the next phase boundary.
5. **Production nginx config check.** Document `X-Accel-Buffering:
   no` requirement in `docs/architecture-harbormaster.md` and
   verify the FleetQ deployment honours it on
   `/api/v1/bridge/mcp/call`. From a11 retro #4.

## Out-of-scope (still)

- Q&A history / federated KG / auto project graph — v1.2 roadmap.
- Backends other than Claude — wait for first user request.
- Plugin / extensions API — v2.
- Tauri / Electron native UI wrapper — post-v1.2.
- Relay-binary path (Path B) — explicitly skipped in favour of Path C.

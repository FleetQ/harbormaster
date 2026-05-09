# Sprint Retro — Harbormaster v3.0.0a1

**Date:** 2026-05-09
**Theme:** Closed the FleetQ → harbormaster `agent.request` publish-surface
loop opened by v2.0.0a7. Inbound bridge events now route through a real
MCP tool dispatcher instead of being logged-and-dropped. First phase of
the v3.0 monolithic line.

## What landed

### `harbormaster` (this repo)

| SHA | Subject |
|-----|---------|
| `226058b` | feat(fleetq): agent.request → MCP dispatcher (v3.0.0a1) |

## Capabilities (this sprint)

### 1 · `agent.request` is no longer a black hole

Before: `BridgeRelay._on_agent_request` logged the inbound event and (since
v2.0.0a7) optionally dispatched to a caller-supplied `chunk_handler`.
Nobody supplied one — the relay was wired in `__main__.py` *without* a
`chunk_handler`, so every inbound MCP call from FleetQ was dropped on the
floor while the relay logged it at INFO level. That's the loop v2.0.0a7
left half-open.

After: `MCPDispatcher(mcp).dispatch` is wired as the chunk_handler whenever
the FastMCP server is constructed. Inbound `agent.request` events now
look up the requested tool in `mcp._tool_manager`, invoke it, serialise
the result, and yield it back as a `client-relay.chunk` event.

Wire shape (response chunk JSON):

```json
// success — single chunk per request
{"result": {"content": [{"type": "text", "text": "<tool result>"}]}}
// tools/list
{"result": {"tools": [{"name": "...", "description": "..."}]}}
// validation / unknown tool / tool exception
{"result": {"isError": true, "content": [{"type": "text", "text": "<msg>"}]}}
```

The relay then publishes the chunk and a final empty `done=true` sentinel
so the FleetQ-side `popChunk` loop closes cleanly.

### 2 · v3 roadmap formalised

`docs/roadmap-v3.md` lays out the 10-phase plan: a1 (this), a2 live bridge
state, a3 pnpm/yarn lockfiles, a4 parallel cross-host recall, a5 pysher
worker-thread, a6 UI token plumbing, a7 inline ask on dashboard, a8
cross-section refresh events, a9 mobile graph + URL state, a10 Playwright
browser tests, then v3.0.0 GA.

## Real numbers

- 1/N v2-retro action items shipped (this is action item #1: "agent.request
  → MCP dispatcher" from v2-final-summary's v3 candidate list)
- 0 PRs opened — per skip-PR-default user preference, merged `feat/v3.0-mcp-dispatcher`
  directly via `git merge --no-ff`
- 12 new unit tests in `tests/unit/test_dispatcher.py`
- Test suite delta: 554 + 1 skip → **566 + 1 skip**
- `mypy --strict` clean across 47 source files
- `ruff` clean across `src/` and `tests/`
- 0 backwards-incompatible changes — `chunk_handler` was already in the
  `BridgeRelay.__init__` signature since v2.0.0a7 with default `None`

## What worked

- **Reuse of an existing seam.** The relay's `chunk_handler` parameter was
  designed in v2.0.0a7 specifically for this hand-off. v3.0.0a1 only had
  to provide the implementation — no relay surface change, no new wire
  contract negotiation with FleetQ. The protocol document
  (`docs/fleetq-relay-protocol.md`) was authoritative; no live FleetQ
  integration test needed before ship.
- **Single-chunk envelope.** Tool results are bounded; streaming per-token
  was tempting but overkill. Yielding one JSON chunk + a `done=true`
  sentinel matches the FleetQ-side `popChunk` contract and avoids a
  partial-result class of bugs. Future per-token streaming for LLM-style
  tools can layer on without changing the envelope.
- **Error envelope vs `client-relay.error` split.** Validation / tool
  errors → `isError: true` MCP envelope (FleetQ sees a normal MCP error
  result). Truly internal failures (handler crash, malformed payload) →
  relay catches and publishes `client-relay.error`. Two distinct paths
  with distinct semantics.

## What to change / next

- **No live FleetQ integration test ran.** Phase 1 ships against the
  protocol doc and a relay smoke test with stub channel — the actual
  end-to-end "FleetQ-side `mcpCall` returns the right answer" was not
  exercised. Plan: drive a smoke from the harbormaster MCP itself
  (eat-our-own-dog-food via `delegate_task`) once a2 lands the live
  bridge state — that gives a real signal to assert against.
- **Routes.py duplication acknowledged but not refactored.** The
  `_dispatch_mcp` helper in `ui/routes.py` does almost exactly what
  `MCPDispatcher._dispatch_envelope` does, with different error
  semantics (HTTPException vs isError envelope). Resisted the
  refactor on YAGNI grounds — they may diverge intentionally as the
  HTTP route adds auth/rate-limit concerns the bridge doesn't need.
  Flag for a v3.x cleanup pass if drift becomes painful.

## Action items for the next sprint (v3.0.0a2)

1. **Live FleetQ runtime state in `/api/bridge/status`.** Today the
   endpoint is config-derived only — returns whether the bridge is
   *configured*, not whether it is *connected*. Add cross-process
   plumbing (file-based `~/.harbormaster/bridge-state.json`) so the
   UI badge can show real connection status, last heartbeat, and last
   error. TTL on read so a stale file renders as "stale" not "down."

## Out-of-scope (still)

- Tauri / Electron desktop UI — no demand; UI is operator-only.
- Relay-binary path (Path B) — Path C HTTP tunnel covers the use case.
- IDE extension (VS Code / JetBrains) — MCP server already works with any
  MCP client.
- Per-token streaming for LLM-style tools through the bridge — single-chunk
  envelope is sufficient for current tool surface.

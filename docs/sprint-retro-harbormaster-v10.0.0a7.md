# Harbormaster v10.0.0a7 — Sprint Retro

**Phase 7 of 8** in the v10.0 alpha chain.

## Shipped

**Inter-project network graph view (Cytoscape vendored).**

A new `/network` page renders an inter-project graph from a new
in-process MCPCallLog ring buffer (last 500 events). Every MCP
tool dispatch the UI sees is recorded; the page subscribes to a
new SSE stream so the graph updates live as new calls land.

## Implementation

New module `src/harbormaster/ui/network_log.py`:
- `NetworkEvent` dataclass:
  `(timestamp_ms, caller, target, tool, status, question_preview)`.
  `question_preview` is hard-truncated to 200 chars — the full
  prompt is never stored in this surface.
- `_MCPCallLog`: ring buffer (max 500). `record()` appends and
  fans out to every active SSE subscriber via per-connection
  `asyncio.Queue` (size 128, non-blocking put — slow consumers
  drop events; ring buffer keeps the canonical record).
- Module-level singleton `network_log`.

Instrumentation (`ui/routes.py`):
- `_emit_chunks_then_result` records one event per completed
  streamed call (ask_project / delegate_task).
- `_dispatch_mcp` records one event per legacy heartbeat-path
  call (recall_qa, project_status, etc.). For `fan_out_ask`,
  one event per resolved target so each leg becomes a distinct
  edge in the graph. Helper `_record_mcp_dispatch()` handles the
  per-tool argument shape.
- Both hooks swallow exceptions — instrumentation must never
  break the user's request.

New routes:
- `GET /network` — page render.
- `GET /api/network/events?limit=N` — `{count, events}` from the
  ring buffer (limit 1..5000).
- `GET /api/network/stream` — SSE; `event` per new record + 5s
  heartbeat; per-connection subscriber queue.

UI (`templates/network.html`):
- Loads vendored `/static/vendor/cytoscape.min.js`.
- Alpine `networkPanel()`: lazy-loads `/api/network/events`,
  subscribes to `/api/network/stream`, builds the Cytoscape
  graph from aggregated edge weights.
- Edge color by tool (cyan = ask, purple = delegate, light-cyan =
  fan_out, emerald = recall).
- Header view-toggle dispatches `hm:network:view` for the
  chat-view alternate (Phase 8 mounts the chat side; Phase 7
  wires the toggle skeleton).

Vendored asset:
- `src/harbormaster/ui/static/vendor/cytoscape.min.js` — Cytoscape
  v3.30.2, MIT, 373KB. Operator-locked decision: vendored, no CDN.
- Already served via the existing `/static/{path}` route.

## Tests (12 new + 3 collateral; +15 net)

`tests/ui/test_network_graph.py`:
- Ring buffer mechanics: append, recent-with-limit, FIFO eviction,
  question preview truncation, subscribe yields new events,
  unsubscribe removes queue.
- HTTP endpoints: `/api/network/events` returns recent + count,
  limit validation (0/10000 → 400), `/network` page references
  Cytoscape vendor + view-toggle markup.
- Vendored cytoscape file present + served via /static/.
- Streaming-path instrumentation hook fires.

## Numbers

- Tests: 1075 → 1090 (+15).
- Source files: 52 → 53 (+1: `network_log.py`).
- mypy --strict: clean.
- ruff: clean.

## Deviations

None. Phase 7 was flagged high-risk (could need an a7.5 split);
it didn't — the in-process ring buffer + module singleton kept
the surface small.

## Risks / Follow-ups

- The ring buffer is per-process. A v11 candidate is to persist
  events to sqlite so the graph survives restarts and aggregates
  across multiple processes.
- `caller` is always "operator" today — the streaming dispatcher
  doesn't yet propagate the originating project when a delegated
  tool calls another tool. v11 could decorate the call chain with
  a `caller_project` arg so true cross-project edges appear.
- EventSource doesn't support custom headers, so the SSE stream
  is bearer-protected via cookie scope rather than header. For
  the operator-on-loopback default install this is fine; future
  hardening would cookie-back the bearer.
- Phase 8 (chat view + toggle) will reuse the same ring buffer
  + SSE feed; only template work + localStorage persistence.

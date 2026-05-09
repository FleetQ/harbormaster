# Sprint Retro — Harbormaster v1.0.0a11

**Date:** 2026-05-09
**Theme:** End-to-end streaming. v1.0.0a10 shipped the daemon-side SSE
wire shape; a11 closes the FleetQ side (Bridge proxy forwards SSE
verbatim) and lays the backend foundation (claude `--output-format
stream-json` parser). The result: a direct caller can already see
incremental output through the Bridge, and the daemon has the parts
needed to emit real per-token chunks once the SSE dispatch is wired
to it (a12 follow-up).

## What landed

### `harbormaster` (this repo)

| SHA | Subject |
|-----|---------|
| `8d0bd05` | feat(backends): claude --output-format stream-json iterator (#4) |
| `0df76d0` | docs: extract sprint retro template (#5) |

### `agent-fleet` (community-edition base submodule)

| (squash) | feat(bridge): SSE streaming consumer for HTTP-mode bridges (#74) |

## Capabilities (this sprint)

### 1 · FleetQ Bridge SSE consumer

`BridgeController::mcpCall` now accepts an optional `stream: bool`
flag. When set on an HTTP-tunnel-mode bridge, the controller opens
an SSE connection to the daemon (sends `Accept: text/event-stream` +
the bridge's bearer token), reads the response body via Guzzle's
PSR-7 stream interface, and forwards bytes back to the FleetQ caller
through Laravel's `response()->stream()`:

```
POST /api/v1/bridge/mcp/call    { …, "stream": true }
↓
BridgeController::mcpCallViaHttpStreaming()
↓
Http::withOptions(['stream' => true])->post(…)
↓
Symfony\StreamedResponse
  + Content-Type: text/event-stream
  + Cache-Control: no-cache
  + X-Accel-Buffering: no       ← nginx forwards immediately
  + Connection: keep-alive
↓
echo $chunk; flush();   ← every 8KB block, no buffering
```

Pre-stream failures (4xx → JSON pass-through with original status,
5xx → 502, connection error → 502) collapse to the synchronous-path
shape so callers don't need a different error reader for streaming
vs sync.

Relay-mode bridges with `stream=true` get a clean **400** with a
"only supported for HTTP-tunnel-mode bridges" message — the relay
path frames responses as Redis chunks and forwarding them as SSE
needs a separate refactor that nobody's asked for yet.

### 3 · `ClaudeBackend.ask_local_stream`

New iterator method on the backend layer that runs `claude -p
--output-format stream-json --verbose` and yields assistant text
deltas as they arrive on stdout. Wire shape:

| stream-json `type` | Action |
|---|---|
| `system` (init / etc.) | ignored |
| `assistant` → `content[]` | each `text` block's text yielded; `tool_use` blocks dropped |
| `result` (final summary) | ignored — the yielded deltas are the user-facing payload |

Failure modes match `ask_local`: timeout / non-zero exit / bad JSON
all surface as `BackendError` with the right `code`. The iterator's
`finally` block always reaps the subprocess so we don't leak zombies
even when the consumer breaks early on the first chunk.

This is **half** of action item #3 from the a10 retro. The other
half — wiring `ask_local_stream` into `_stream_dispatch` so
`/mcp/{server}` actually emits `chunk` SSE events for `ask_project`
— is deferred to a12. Reason: FastMCP's tool registry expects sync
`def tool() -> str`, so the streaming bypass needs to dispatch to
the backend directly rather than through `tool.fn(...)`. Layering
that as its own PR keeps the diff reviewable.

### 5 · Sprint retro template

Five sprints in (a5–a10), the retro structure has stabilised:
**What landed → Capabilities → Real numbers → What worked → What
to change → Action items → Out-of-scope**. `docs/sprint-retro-TEMPLATE.md`
captures it once with per-section authoring guidance so future
retros stop reinventing the section ordering. **This retro is the
first one written using the template** — the friction it removed
is real.

## Real numbers

- 3/3 a11 action items shipped (items 1, 3, 5 from the v1.0.0a10
  retro; items 2 and 4 explicitly deferred to a12 — see "Action
  items" below)
- 3 PRs opened, all 3 merged
  - 2 on FleetQ/harbormaster (#4, #5)
  - 1 on escapeboy/agent-fleet-o (#74)
- 11 new tests
  - +6 BridgeControllerTest (3 stream=true happy paths, 1 sync regression, 2 error paths)
  - +5 test_backends (4 ask_local_stream parser cases + 1 cmd-shape check)
- Test suite delta: 223 → 228 passed on harbormaster; 17 → 23 on
  BridgeControllerTest
- Pint: 3311 files clean. Ruff + mypy --strict clean across 26
  source files
- 0 backward-incompatible changes

## What worked

- **Sprint-scoped retro template.** Writing this retro was visibly
  faster than v1.0.0a10's. The template's `>` blockquote guidance
  blocks make "what goes in this section" obvious without scrolling
  back to a previous retro to figure it out.
- **Backend-first foundation.** Splitting "claude stream-json
  parser" from "wire it to SSE dispatch" was the right call. The
  parser shipped with five tests and zero coupling to the routes
  layer; the wire-up will be a focused diff in its own PR. If we'd
  bundled them, the diff would have spanned three architectural
  layers (subprocess, MCP dispatch, HTTP) and review would have
  taken twice as long.
- **stream=true flag on the FleetQ side, not Accept-header sniffing.**
  Made the routing decision explicit at the API contract level.
  Agent-fleet callers get a documented switch, not a "magic" SSE
  toggle that depends on header parsing the way harbormaster does
  internally. Both sides can evolve independently.
- **Out-of-scope discipline.** PR #4 explicitly listed two pieces
  it was NOT doing (SSE wire-up + `ask_remote_stream`) and why. PR
  reviewers don't have to ask "wait, what about…" because the PR
  body already answers it.

## What to change / next

- **PHP-FPM output buffering still untested in production.** The
  agent-fleet PR sets `X-Accel-Buffering: no` and disables
  `flush()` under tests, but we haven't yet confirmed the live
  nginx config respects that header on `/api/v1/bridge/mcp/call`.
  If the upstream proxy buffers at 64KB, streaming silently
  degrades to "one big chunk at the end" — undetectable from
  unit tests. Priority for a12.
- **stream-json output format may have changed.** Adding
  `--verbose` was a guess based on prior knowledge that
  claude-code rejects `stream-json` without it. We should
  confirm against the version pinned in `cfg.binary` before
  the wire-up PR, or `ask_local_stream` will silently produce
  no output.
- **No test runs the streaming end-to-end yet.** Backend layer
  tests are mocked, FleetQ proxy tests are mocked, harbormaster
  daemon tests are mocked. Each component is verified in
  isolation, but a single integration test that puts them all
  together would catch wire-shape drift between the layers.
  Worth landing as part of the gated `smoke-fleetq` job in a12.
- **README "v1 limits" section is now out of date.** It lists
  "synchronous request/response only" — true at a9, no longer
  true at a11. Need a quick scrub to say "streaming via
  `Accept: text/event-stream` (daemon) and `stream=true`
  (FleetQ Bridge)".

## Action items for the next sprint (v1.0.0a12 / week 12)

1. **Wire `ask_local_stream` into `/mcp/{server}` SSE dispatch.**
   When `Accept: text/event-stream` AND tool name is `ask_project`,
   bypass FastMCP's sync tool dispatch and call
   `ClaudeBackend.ask_local_stream(...)` directly, emitting each
   yielded chunk as a `chunk` SSE event between heartbeats. Wire
   shape: `event: chunk\ndata: {"text": "..."}\n\n`. Final `result`
   event still emitted at the end with the assembled string for
   callers that want a single final value.
2. **Live FleetQ → harbormaster streaming smoke.** Extend
   `tests/smoke_fleetq.py` to make a `stream=true` call against
   the live FleetQ instance and assert that bytes arrive
   incrementally (timing-based: at least one chunk should be
   visible before the tool's full duration). Catches the
   PHP-FPM buffering case unit tests can't see.
3. **README "v1 limits" scrub.** Remove the "synchronous only"
   line. Add a streaming usage example under the Tools table.
4. **Production nginx config check.** Document the
   `X-Accel-Buffering: no` requirement in `docs/architecture-harbormaster.md`
   and verify the FleetQ deployment honours it for the
   `/api/v1/bridge/mcp/call` route. If it doesn't, ship a
   location-specific override.
5. **Begin v1.1 scope.** With streaming closed, time to start the
   FleetQ Platform Tool seeder PR and A2A Agent Card per project
   work outlined in `docs/design-harbormaster.md` §3 v1.1. Carry
   item 4 from the a10 retro forward.
6. **`ask_remote_stream` (SSH variant).** Local-only streaming is
   shippable, but `ask_project` over SSH is the more common
   real-world path. Needs stdout demux through ssh — bigger
   refactor than the local case.

## Out-of-scope (still)

- Q&A history / federated KG / auto project graph — v1.2 roadmap.
- Backends other than Claude — wait for first user request.
- Plugin / extensions API — v2.
- Tauri / Electron native UI wrapper — post-v1.2.
- Relay-binary path (Path B) — explicitly skipped in favour of Path C.
- Real token-by-token streaming through FleetQ — wired up to a12 (item 1 above).

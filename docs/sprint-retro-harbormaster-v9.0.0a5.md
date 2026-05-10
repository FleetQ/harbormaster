# Sprint Retro — Harbormaster v9.0.0a5

**Date:** 2026-05-10
**Phase:** v9.0 Phase 5 — Typed SSE events
**Branch:** `feat/v9.0-typed-sse-events`

## What shipped

The chunk pipeline behind ask_project / delegate_task / fan_out_ask
now emits typed events (`token`, `usage`) alongside the legacy
`chunk` event. The browser-side consumer prefers the typed events
when both are available; clients that only listen for `chunk` keep
working unchanged.

| Artifact                                              | Purpose                                                                  |
|-------------------------------------------------------|--------------------------------------------------------------------------|
| `_emit_chunks_then_result` dual emit                  | Each delta yields `chunk` + `token`; final yields `usage` then `result`  |
| `usage` event payload                                 | Best-effort: `output_chunks`, `output_chars`, `approximate: true`        |
| `_ask_form_script.html` consumer migration            | `preferTokenEvents` flag suppresses double-counting; `tool` + `usage` handlers |
| `tests/ui/test_typed_sse_events.py`                   | 10 tests pinning event order + payloads                                  |
| Test updates: `test_ui.py` + `test_sse_last_event_id` | Updated to expect the new `[chunk, token, chunk, token, usage, result]` sequence |

## Numbers

* **Tests:** 992 → 1002 (+10 net; +1.0%) — 3 existing tests updated, 10 new added
* **Source files:** 52 → 52
* **Per-delta wire overhead:** one extra SSE frame (`token` event) — same data payload as the corresponding `chunk` event but with `delta` instead of `text`. Negligible additional bytes (~30B per delta).
* **mypy --strict + ruff:** clean
* **Backwards-incompatible:** 0 user-facing — the `chunk` event continues to fire with the same `{"text": ...}` shape

## Event taxonomy (v9.0.0a5)

```
event: chunk          ← LEGACY, removed in v10
data: {"text": "..."}

event: token          ← NEW, primary text-delta channel
data: {"delta": "..."}

event: tool           ← NEW, currently emitted by the trace surface; placeholder
data: {"tool_name": "...", "phase": "start"|"end", ...}

event: usage          ← NEW, just before result
data: {"output_chunks": N, "output_chars": M, "approximate": true}

event: result         ← unchanged
data: <MCP envelope>

event: error          ← unchanged
data: {"status": N, "detail": "..."}

event: heartbeat      ← unchanged
data: {"elapsed_ms": N}
```

Every event keeps its v9.0.0a4 monotonic SSE `id:` line.

## Deviations from the phase plan

### 1 · Real token counting deferred to v10

**Plan said:** "`usage` `{input_tokens: N, output_tokens: N, model: "..."}`".

**What shipped:** `{output_chunks, output_chars, approximate: true}`.

**Why:** the backends (Claude CLI / Codex CLI) emit text deltas via
their stdio pipe; they don't surface per-call token counters or
model identity through the streaming interface. Plumbing real
token counts requires either:

  (a) Parse the backend CLI's terminal accounting output (model-
      specific, fragile, breaks across CLI versions).
  (b) Add an `--output-format json` flag to the backend invocations
      and parse the structured response (requires a backend-side
      refactor that owns its own alpha).

The chunk count + char count is the directional signal the
dashboard needs today — operators can see *something* about the
volume of work; the `approximate: true` flag tells consumers not
to bill against it. Real token counters land in v10 alongside the
backend instrumentation phase.

### 2 · `tool` event is wire-format-only this phase

**Plan said:** the `tool` event signals "MCP tool calls" inside an
agent run. The dashboard's chunk pipeline today doesn't see those
sub-tool calls — they happen inside the backend's process and only
their text output shows up.

**What shipped:** the client (`_ask_form_script.html`) handles a
`tool` event if it ever sees one (renders inline `[tool start: name]`
badge), but no path emits it yet. The client wiring is the safe
half — backend instrumentation that emits the events is a v10
candidate.

### 3 · Three pre-existing tests rewritten

`tests/unit/test_ui.py::test_stream_ask_project_local_yields_chunk_events_and_final_result`,
`tests/unit/test_ui.py::test_stream_local_tool_delegate_task_yields_chunks`,
and `tests/ui/test_sse_last_event_id.py::test_emit_chunks_then_result_yields_ids`
all asserted the `[chunk, chunk, result]` sequence. With dual-emit
they now expect `[chunk, token, chunk, token, usage, result]`.

This is **not a contract change** — it's the test catching up to
the additive event surface. Both the old `chunk` data field
(`text`) and the new `token` data field (`delta`) are asserted in
the updated tests so future refactors that drop one or the other
fail loudly.

## What worked

* **Dual-emit + client preference flag.** The cleanest no-breaking
  way to migrate consumers. Server emits both; client picks one and
  ignores the other; v10 just deletes the legacy emit + the
  `preferTokenEvents` flag.
* **Wire-format-only `tool` event support on the client.** Lets us
  ship the JSON shape contract today; backend instrumentation can
  follow without UI churn.
* **`approximate: true` flag on usage.** Honest about the
  measurement; consumers can ignore the values if they need real
  token counts.

## What we'd do differently

* **Add a `usage` event aggregator endpoint.** Right now `usage`
  fires per-stream; aggregating across recent dispatches needs a
  separate aggregator (or a sweep through `DispatcherStats` plus
  whatever the backend instrumentation eventually surfaces).
  Defer to v10 backend-instrumentation phase.
* **Document the deprecation in the README's "API stability"
  section.** Operators consuming the SSE wire directly need to
  know the timeline. Currently only the v9.0.0a5 retro + the
  source comments call it out.

## Forward to v9.0.0a6

Phase 6: Sidebar enhancements (Archived group, rail-collapse,
per-host filter) + `stateBadge` helper unification + palette
dynamic-action search. Three v8-deferred items consolidated into
one polish phase.

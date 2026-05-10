# Sprint Retro — Harbormaster v9.0.0a4

**Date:** 2026-05-10
**Phase:** v9.0 Phase 4 — SSE Last-Event-ID resumption
**Branch:** `feat/v9.0-sse-last-event-id`

## What shipped

The dispatcher trace stream now resumes cleanly after a dropped
connection. Every SSE event across the dashboard's streaming
surfaces also gains an `id:` line — the protocol prerequisite that
v7's deferral list flagged as needed for backwards-compatible
client-driven resumption.

| Artifact                                     | Purpose                                                                  |
|----------------------------------------------|--------------------------------------------------------------------------|
| `_StreamIdSeq`                               | Per-stream monotonic SSE event id generator                              |
| `/api/dispatcher/trace` Last-Event-ID parse  | Reads request header, replays span_end events from ring buffer           |
| `ready` event payload `resumed_from`         | Tells the client what cursor the server interpreted                      |
| `_stream_dispatch` heartbeat / result / error | Each emitted event carries an `id:`                                       |
| `_emit_chunks_then_result` chunk pipeline    | Each chunk + final result + error event carries an `id:`                 |
| `tests/ui/test_sse_last_event_id.py`         | 7 tests — _StreamIdSeq, replay logic, no-header backwards compat, garbage handling |

## Numbers

* **Tests:** 985 → 992 (+7; +0.7%)
* **Source files:** 52 → 52 (helper class added inside existing routes module)
* **mypy --strict + ruff:** clean
* **Backwards-incompatible:** 0 user-facing
* **Per-event overhead:** one integer increment + a string format. Negligible.

## Resumption protocol (canonical)

1. Client connects to `/api/dispatcher/trace`.
2. Server emits `ready` carrying `{available, resumed_from}` where
   `resumed_from` is whatever integer was in `Last-Event-ID` (`0`
   on first connect or garbage values).
3. Server replays `span_end` events from the ring buffer where
   `span_id > resumed_from`. (Bounded by the v9.0.0a3 ring buffer
   max of 100; older spans are lost.)
4. Server resumes the live tail.
5. Every event carries an `id:` line equal to `span_id` — browser
   EventSource records the highest-seen id automatically.
6. On disconnect → reconnect, `Last-Event-ID` is sent automatically
   by the browser; loop returns to step 2.

The trace surface page (`dispatcher_trace.html` from v9.0.0a3) needs
no client-side changes — `EventSource` handles the header round-trip
natively. Custom polyfills (rare in this codebase — only the
`_ask_form_script.html` uses fetch-based SSE) are out of scope until
the typed-events phase a5 lands.

## Deviations from the phase plan

### 1 · Client-side exponential backoff not implemented

**Plan said:** "Reconnect strategy: exponential backoff (1s, 2s,
4s, max 8s) up to 3 attempts before surfacing error."

**What shipped:** native browser EventSource reconnection only. The
browser has its own reconnect strategy (typically a few-second
delay; configurable per-stream via the SSE `retry:` field, which
sse-starlette emits by default). No custom 3-attempt cap.

**Why:** the plan's specified backoff requires either:

  (a) Switching every SSE consumer from `EventSource` to a custom
      fetch + ReadableStream + manual reconnect loop. That's a 200+
      line client implementation duplicated wherever SSE is consumed
      (dispatcher trace, ask form, fan-out, delegate). High-blast,
      high-test surface.
  (b) Using a polyfill like `eventsource-polyfill`. Adds a new CDN
      dep; the page-weight / ops budget already hit the v9 plan's
      "trim CDN reliance" theme.

The browser's native reconnect behavior already handles the common
case (network blip → reconnect → server replays missed spans via the
new Last-Event-ID logic). Operators who hit a 3-attempt-then-error
constraint are running degraded networks where the right fix is
elsewhere. v10 candidate: a fetch-based EventSource shim that
unifies the reconnect strategy across all consumers.

### 2 · Replay is span_end-only

**Implementation detail worth flagging:** the server replays `span_end`
events from the ring buffer, not `span_start`. By the time a client
reconnects, every span that completed during the disconnect is
finished anyway — the start event is informationally redundant. The
client's renderer only needs the final state. (If a span is *still
in flight* when the client reconnects, the live tail picks it up
naturally.)

This means a client reconnecting mid-burst sees:
  * `ready` with `resumed_from=N`
  * a sequence of `span_end` events for spans N+1 .. M
  * the live tail (more `span_start` / `span_end` for newer work)

The client-side `traceWaterfall()` already handles this — `_onSpanEnd`
just unconditionally adds the completed span to the recent list.

## What worked

* **Reusing `span_id` as the SSE event id.** It's already monotonic,
  process-wide, set in v9.0.0a3 — no new identity to maintain.
* **`request.headers.get("last-event-id")` with `int(...)` + try/except.**
  Tiny parser, garbage-tolerant. The Last-Event-ID spec is just
  "pass back whatever you got" — it doesn't have a type.
* **Ring buffer replay is bounded by construction.** 100 events
  max; the worst case is one O(100) walk per reconnect. Cheap.

## What we'd do differently

* **Document the "spans older than the ring buffer are lost"
  caveat in operator-facing docs.** A client that disconnects for
  longer than the buffer takes to fill (a handful of seconds at
  high dispatch rates) will miss data. Either bump the ring max
  or warn operators that the trace surface is lossy.
* **Land the typed-events refactor (Phase 5 next) BEFORE adding any
  more SSE consumers.** Each new consumer that listens for `chunk`
  events makes the eventual migration to `token` / `tool` / `usage`
  events more painful — the additive-coexistence window the v9 plan
  promises buys time, but only one full version of it.

## Forward to v9.0.0a5

Phase 5: Typed SSE events. Replace generic `chunk` with `token`,
`tool`, `usage`, `error`, `result`. Backwards-compat: emit `chunk`
alongside `token` for one full version (deprecation in v9 retro,
removal in v10). The trace surface from a3 already uses typed
events (`span_start` / `span_end`); a5 brings the same discipline
to the dispatch / ask-form streams.

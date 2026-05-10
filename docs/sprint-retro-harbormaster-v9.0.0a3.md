# Sprint Retro — Harbormaster v9.0.0a3

**Date:** 2026-05-10
**Phase:** v9.0 Phase 3 — Trace waterfall surface
**Branch:** `feat/v9.0-trace-waterfall`

## What shipped

A new `/dispatcher` page that streams live tool-dispatch spans
over SSE and shows the last-100 completed dispatches as a
single-row timeline. The original v8 phase plan reserved this for
v9; v9.0.0a3 ships it as a single coherent surface.

| Artifact                                                       | Purpose                                                                |
|----------------------------------------------------------------|------------------------------------------------------------------------|
| `DispatcherStats` ring buffer + subscription fan-out           | Last-100 completed spans + per-consumer event queue                    |
| `record_start` adds a monotonic `span_id`                      | Lets clients pair `span_start` ↔ `span_end` events                     |
| `GET /dispatcher`                                              | Alpine `traceWaterfall()` page with In-flight + Recent sections        |
| `GET /api/dispatcher/recent?limit=N`                           | First-paint payload for the Recent section                             |
| `GET /api/dispatcher/trace`                                    | SSE: `ready`, `span_start`, `span_end`, `heartbeat` events             |
| `dispatcher_trace.html` template                               | Single-row timeline (bars scaled vs. max duration in view)             |
| Nav link in `base.html`                                         | Dashboard → Fan-out → Dispatcher                                       |
| `tests/ui/test_dispatcher_trace_endpoint.py`                   | 11 tests — page render, recent shape, fanout, ring buffer cap, SSE probe |

## Numbers

* **Tests:** 971 → 985 (+14; +1.4%)
* **Source files:** 52 → 52 (template + handler reuse existing modules)
* **Templates:** 5 → 6 (`dispatcher_trace.html`)
* **mypy --strict + ruff:** clean
* **Backwards-incompatible:** 0 user-facing
* **DispatcherStats overhead:** unchanged on the hot path
  (`record_start` / `record_end` already grabbed the lock; the new
  fan-out walks `self._subscribers` under the same lock — typically
  0 or 1 entry).

## SSE event format (canonical)

The page subscribes to `/api/dispatcher/trace` with `EventSource` and
listens for the following events:

```
event: ready
data: {"available": true}

event: span_start
data: {"span_id": 1, "tool": "ask_project", "project": "demo", "started_at": 1700000000.0}

event: span_end
data: {"span_id": 1, "tool": "ask_project", "project": "demo", "started_at": 1700000000.0, "ended_at": 1700000002.5, "ok": true}

event: heartbeat
data: {"ts": 1700000005.0}
```

`span_id` is process-wide monotonic, so reconnecting clients can
de-duplicate the events they've already seen against the
`recent` payload they fetched at connect time.

## Deviations from the phase plan

### 1 · Single-row timeline, not parent/child waterfall

**Plan said:** "Render as horizontal waterfall: agent invocation = root
span, tool calls = child spans, each token batch = leaf".

**What shipped:** flat single-row-per-span timeline. Each dispatch
is one bar; bar width scales against the longest in the visible set.
No parent/child relationships, no token-level leaf spans.

**Why split:** the dispatcher only knows about *one level* of spans —
the tool dispatch itself. To make a real parent/child waterfall, we'd
need either:

  (a) Instrumentation **inside** the tool implementations (e.g., for
      `ask_project`, emit a child span per backend round-trip + per
      token batch). That's an O(N) refactor across every backend +
      tool function.
  (b) An OpenTelemetry SDK integration where backends auto-emit child
      spans against the dispatcher's trace context. Heavy dep — the
      whole point of "lightweight — no real OpenTelemetry SDK; just
      structured event records" in the plan was to dodge this.

The plan's escape hatch authorizes this exact split: *"If full
waterfall is too much for one phase: ship the SSE event format + the
new route + a list view (no waterfall viz). The viz can be a v9.0.0a3.5
follow-up."* Single-row-per-span is the canonical "list view with
duration bars" — visually informative, parent/child viz reserved for
v10's potential D3 / Cytoscape upgrade.

### 2 · SSE wire test simplified to direct generator probe

**Plan said:** "Tests: `tests/ui/test_dispatcher_trace_endpoint.py`
+ Playwright assertion that `/dispatcher` renders + SSE stream
produces span events".

**What shipped:** the unit-level test calls the registered route
handler directly with a stub `Request` whose `is_disconnected()`
returns `True` after the first `ready` event, then drives one
yielded event from `EventSourceResponse.body_iterator`.

**Why:** `TestClient.stream("GET", "/api/dispatcher/trace")` blocks
on `iter_text()` because the handler stays open for the lifetime of
the request — there's no graceful "drain one event then close" hook.
Documented in `~/.claude/projects/-Users-katsarov/memory/feedback_sse_streamed_response_test_friction.md`.
The Playwright assertion is reserved for the v9 GA browser smoke
suite.

## What worked

* **Reusing the v9.0.0a2 singleton.** `record_start` and `record_end`
  already had the right lock-scope; adding fan-out + ring buffer was
  ~30 lines and didn't change the dispatch-side hot path overhead
  (the fan-out runs under the same lock so we don't pay an extra
  acquire per event).
* **`deque(maxlen=...)` for both ring buffer and per-subscriber
  queue.** Drops oldest on overflow without explicit checks. Python
  stdlib at its best.
* **First-paint via /api/dispatcher/recent + live via SSE.** Splitting
  the bootstrap from the live stream means the page has content
  *immediately* on render (no SSE-completion-before-paint UX glitch).
* **Bar-width scaled to in-view max.** Avoids the "1ms span looks
  identical to a 30s span when both share the same axis" problem.
  Live spans stretch as they run; on completion they snap to the
  same scale as their peers.

## What we'd do differently

* **A `last_event_id` query param on `/api/dispatcher/trace`.**
  Phase 4 (next alpha) implements SSE Last-Event-ID resumption
  generically — when it lands, the trace stream gets that for free.
  But documenting "events between disconnect and reconnect can be
  lost" up-front would have been honest.
* **A density mode for the Recent section.** 100 spans on screen
  can be a lot of vertical scroll. v10 candidate: a virtual-scroll
  list or a "group by tool" toggle.
* **A column-sort mode.** Currently sort = chronological-newest-first.
  Operators may want "longest first" or "errored first". Cheap to
  add — Alpine + a sort-key dropdown.

## Forward to v9.0.0a4

Phase 4: SSE Last-Event-ID resumption. The trace stream from a3 will
inherit it once the generic mechanism lands.

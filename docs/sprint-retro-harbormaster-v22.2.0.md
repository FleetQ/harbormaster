# Sprint Retro — Harbormaster v22.2.0

**Date:** 2026-05-12
**Theme:** Push channels for delegated jobs. New SSE stream at
``/api/delegated-jobs/stream`` for the operator dashboard /jobs page
(live row updates without reload); new MCP resources at
``harbormaster://jobs/recent`` and ``harbormaster://jobs/{job_id}``
for client-side discovery. Both backed by the v22.1.0 JobStore
subscriber hook.

## What landed

| File | Subject |
|---|---|
| `src/harbormaster/jobs/broadcaster.py` | new — ``JobEventBroadcaster`` threadsafe → asyncio bridge |
| `src/harbormaster/jobs/subsystem.py` | wires broadcaster as JobStore subscriber on subsystem init |
| `src/harbormaster/jobs/__init__.py` | exports ``JobEventBroadcaster`` |
| `src/harbormaster/ui/routes.py` | new ``GET /api/delegated-jobs/stream`` SSE endpoint |
| `src/harbormaster/ui/templates/jobs.html` | Alpine ``connectStream`` / ``_applyJobUpdate`` — live patch rows + summary on every event |
| `src/harbormaster/tools/job_resources.py` | new — MCP resource exposure (``harbormaster://jobs/recent`` + per-id template) |
| `src/harbormaster/tools/__init__.py` | registers resource module |
| `tests/unit/test_jobs_broadcaster.py` | new — 5 broadcaster unit tests |
| `tests/integration/test_jobs_sse_stream.py` | new — 5 wiring + MCP-resource tests |
| `src/harbormaster/__init__.py` | 22.1.0 → 22.2.0 |
| `docs/sprint-retro-harbormaster-v22.2.0.md` | this file |

## Capabilities

### SSE push for the dashboard

- ``GET /api/delegated-jobs/stream`` — server-sent events.
  - ``event: event`` frames carry the full ``Job.as_dict()`` payload
    of a job that just landed in a terminal state.
  - ``event: heartbeat`` frames at the network-stream cadence
    (default 30 s; configurable via
    ``[server] heartbeat_interval_network_s``).
- ``/jobs`` page connects on load via ``EventSource``; closes on
  ``beforeunload``. New completions / failures patch the visible
  table row in place (or insert / remove based on the active filter)
  and refresh the counter strip.

Net effect: a fan-out batch displays on the operator screen the
moment each job lands — no manual reload, no polling interval.

### MCP resources

- ``harbormaster://jobs/recent`` — static resource. Returns the top
  50 jobs (newest first) as a JSON-encoded array of dicts.
- ``harbormaster://jobs/{job_id}`` — parametrised resource template.
  Returns one job dict; ``{"error": "not_found", "job_id": ...}``
  for unknown ids.

These make jobs discoverable through any MCP client's resource UI
(e.g., Claude Desktop's "Available Resources" panel) without
requiring a tool call.

### JobEventBroadcaster

A small pubsub class that bridges the JobStore subscriber hook (sync,
runs on the worker thread) to asyncio consumers. ``subscribe()`` is
called from inside an asyncio coroutine and captures the running
loop reference; ``publish_threadsafe()`` is called from any thread
and dispatches via ``loop.call_soon_threadsafe``. Loop-closed
subscribers (e.g., disconnected SSE clients) are silently pruned on
publish — ``RuntimeError`` is suppressed.

Pattern mirrors ``harbormaster.ui.network_log.network_log`` for
mcp_calls events.

## Numbers

- 11 files (5 new). ~330 LOC.
- 1998 → 2008 tests (+10). mypy --strict clean on 69 source files.
  ruff src/ tests/ clean.

## Design notes

### Subscriber wiring happens in the subsystem boot

``get_subsystem`` creates the broadcaster *after* the store and worker
are constructed, then calls ``store.add_subscriber(broadcaster.
publish_threadsafe)``. This is the only wiring point — every consumer
(SSE endpoint, future webhook layer, future Pusher push) opens its
own queue against the broadcaster, not the JobStore.

Decoupling the broadcaster from the store keeps the store's
threading model (single-lock SQLite + simple subscriber list)
unchanged from v22.1.0. The store doesn't know what shape the
subscribers want (Job vs dict vs SSE frame) — it just hands them the
``Job`` and lets them transform.

### TestClient cannot consume infinite EventSourceResponse cleanly

Same constraint that drove ``tests/ui/test_heartbeat_tuning.py`` to
test ``/api/network/stream`` at the source level: the test client
holds the generator open and never cancels it. The first sketch of
``test_jobs_sse_stream.py`` had a streaming test that hung forever.
Replaced with structural tests:

- subscriber wiring (probe registered on store)
- route registration (path is in ``app.routes``)
- broadcaster invocation on complete (via probe subscriber)

The actual SSE behaviour is exercised manually against the running
daemon — the dashboard /jobs page acts as a continuous live test.

### MCP resources are discovery, not push

FastMCP exposes ``@mcp.resource()`` and supports both static URIs and
parametrised templates. Subscriptions
(``resources/subscribe`` → ``notifications/resources/updated``) are
defined in the MCP spec but client-side surfacing varies; Claude
Desktop reads resources on demand but doesn't auto-resume a session
on update.

Treating MCP resources as discovery (list + read on demand) and
keeping push on the SSE side is the pragmatic split. When clients
gain reliable subscription surfacing, the JobStore subscriber hook is
already there to feed it — only a small notifier shim needs adding.

### Heartbeat reuses the network cadence

``[server] heartbeat_interval_network_s`` (default 30 s) governs both
``/api/network/stream`` and ``/api/delegated-jobs/stream``. Same
"events are infrequent, frequent heartbeats are pure noise" logic
applies. Separate tuning was considered and rejected as premature.

## Lessons

### Threadsafe → asyncio bridges always need a captured loop

Subscriber lives on the JobWorker thread; consumer lives on the
uvicorn asyncio loop. ``asyncio.Queue`` is not threadsafe; you must
schedule the put via ``loop.call_soon_threadsafe``. ``subscribe()``
must be called from inside the asyncio coroutine (so
``get_running_loop()`` works) and pair the queue with that loop.
Easy to get wrong — captured in the broadcaster doc + tested by
explicitly running ``publish_threadsafe`` from a real
``threading.Thread`` in the unit suite.

### Subsystem composition keeps wiring in one place

Adding a fourth field to the ``Subsystem`` dataclass and wiring it
in ``get_subsystem`` is the only place v22.2.0 touched the boot
sequence. Tools and HTTP handlers all reach through
``get_subsystem(config)`` — no transport-specific globals creeping
in. Pattern carries forward cleanly when v23 adds a multi-worker
config knob or Pusher push.

## Carry-over to v23

1. Multi-worker concurrency (config knob ``[delegate] worker_count``;
   atomic ``UPDATE ... RETURNING`` already supports it).
2. Cross-tenant inbox isolation (auth-gated ``inbox_id``).
3. FleetQ Bridge push channel (publish completion events to Pusher;
   external agents subscribe).
4. ``mcp__harbormaster__notifications/resources/updated`` push when
   FastMCP / clients gain reliable subscription forwarding.
5. Pagination on ``/api/delegated-jobs`` (currently capped at 1000).

## Operator-facing note

After upgrading to v22.2.0:

- ``/jobs`` page now updates live — no manual reload required.
  EventSource auto-reconnects on transient network errors (browser
  default). If the dashboard daemon is restarted, the page reconnects
  within a few seconds.
- Heartbeats appear in ``ui.log`` as ``GET /api/delegated-jobs/stream
  HTTP/1.1 200`` lines that never end — that's expected SSE
  behaviour. The connection lifetime is bounded by the operator
  closing the tab, not by request timeouts.
- MCP resources visible in Claude Desktop / other MCP clients:
  ``harbormaster://jobs/recent`` (static), ``harbormaster://jobs/{id}``
  (template). Clients with resource discovery can browse delegated
  jobs without invoking ``get_delegated_task``.
- ``recall_pending_results`` / ``await_inbox`` / ``await_delegated_task``
  are unchanged — pull/blocking-await still works for any MCP client.

"""Dispatcher UI surface (v9+).

Extracted from ``routes.py`` in v23.0.0a4 — third step of the routes
split. Four endpoints:

  GET /dispatcher                  HTML trace waterfall
  GET /api/dispatcher/recent       most-recent completed spans
  GET /api/dispatcher/trace        SSE: live span_start / span_end
  GET /api/dispatcher/status       runtime counters snapshot

Falls back to canonical-empty responses when the [fleetq] extra is
missing — same shape as the inline block had pre-v23.0.0a4.
"""
from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator, Callable
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from sse_starlette.sse import EventSourceResponse

from harbormaster.config import HarbormasterConfig

RenderFn = Callable[[Request, str, dict[str, Any]], HTMLResponse]


def register_dispatcher_routes(
    app: FastAPI, config: HarbormasterConfig, render: RenderFn,
) -> None:
    """Wire the /dispatcher + /api/dispatcher/* endpoints onto ``app``."""

    @app.get("/dispatcher", response_class=HTMLResponse)
    async def dispatcher_page(request: Request) -> HTMLResponse:
        """v9.0.0a3: trace waterfall surface.

        Single-page view of live + recent dispatcher activity. The page
        consumes ``GET /api/dispatcher/trace`` (SSE) for live spans and
        ``GET /api/dispatcher/recent`` for the last-N completed spans
        on first paint.
        """
        return render(request, "dispatcher_trace.html", {})

    @app.get("/api/dispatcher/recent")
    async def api_dispatcher_recent(limit: int = 20) -> dict[str, object]:
        """v9.0.0a3: most-recently completed dispatcher spans.

        Bounded by the singleton's ring buffer (currently 100 spans).
        Returns up to ``limit`` (clamped to [1, 100]).
        """
        try:
            from harbormaster.fleetq import get_dispatcher_stats
        except ImportError:
            return {"spans": []}
        clamped = max(1, min(int(limit), 100))
        return {"spans": get_dispatcher_stats().recent_completed(clamped)}

    @app.get("/api/dispatcher/trace")
    async def api_dispatcher_trace(request: Request) -> EventSourceResponse:
        """v9.0.0a3: live span_start/span_end SSE stream.

        Each event's ``data`` is a JSON object with the span shape
        documented in ``DispatcherStats.subscribe`` — at minimum
        ``{kind, span_id, tool, project, started_at, [ended_at, ok]}``.
        Heartbeats every ``_HEARTBEAT_INTERVAL_S`` seconds keep the
        connection alive through nginx/Cloudflare 60s idle timeouts.

        v9.0.0a4: each event carries an SSE ``id`` field equal to the
        event's `span_id` (process-monotonic). On reconnect, clients
        SHOULD send a ``Last-Event-ID`` header carrying the highest
        `span_id` they have already processed; the server replays any
        completed spans with `span_id > last` from the ring buffer
        before resuming the live tail.
        """
        last_event_id_raw = request.headers.get("last-event-id")
        last_event_id: int = 0
        if last_event_id_raw:
            try:
                last_event_id = max(0, int(last_event_id_raw))
            except ValueError:
                last_event_id = 0

        async def gen() -> AsyncIterator[dict[str, str]]:
            try:
                from harbormaster.fleetq import get_dispatcher_stats
            except ImportError:
                yield {"event": "ready", "data": json.dumps({"available": False})}
                return
            stats = get_dispatcher_stats()
            sub = stats.subscribe()
            yield {
                "event": "ready",
                "data": json.dumps(
                    {"available": True, "resumed_from": last_event_id}
                ),
            }
            if last_event_id > 0:
                for span in stats.recent_completed(limit=100):
                    if int(span["span_id"]) <= last_event_id:
                        continue
                    yield {
                        "event": "span_end",
                        "id": str(span["span_id"]),
                        "data": json.dumps(
                            {
                                "span_id": span["span_id"],
                                "parent_span_id": span.get("parent_span_id"),
                                "trace_id": span.get("trace_id"),
                                "tool": span["tool"],
                                "project": span["project"],
                                "started_at": span["started_at"],
                                "ended_at": span["ended_at"],
                                "ok": span["ok"],
                            }
                        ),
                    }
            last_heartbeat = time.time()
            try:
                while True:
                    if await request.is_disconnected():
                        break
                    events = sub.drain()
                    for ev in events:
                        kind = ev.pop("kind")
                        yield {
                            "event": kind,
                            "id": str(ev.get("span_id", "")),
                            "data": json.dumps(ev),
                        }
                    if events:
                        last_heartbeat = time.time()
                    elif (
                        time.time() - last_heartbeat
                        >= config.server.heartbeat_interval_trace_s
                    ):
                        yield {
                            "event": "heartbeat",
                            "data": json.dumps({"ts": time.time()}),
                        }
                        last_heartbeat = time.time()
                    await asyncio.sleep(0.1)
            finally:
                stats.unsubscribe(sub)

        return EventSourceResponse(gen())

    @app.get("/api/dispatcher/status")
    async def api_dispatcher_status() -> dict[str, object]:
        """Live runtime metrics for the in-process MCP dispatcher (v9.0.0a2).

        Replaces the v8.0.0a5 KPI placeholder ``"ready"`` with a real
        counters payload so the dashboard's KPI strip + the v9 trace
        waterfall can both read from the same source.

        Schema:
        ```
        {
          "running": [{"tool": str, "project": str | null, "started_at": float}, ...],
          "active_workers": int,         # sum of in_flight across tools
          "queue_depth": int,            # always 0 for in-process dispatcher
          "last_dispatched_at": float | null,
          "tools": {
            "<tool_name>": {"in_flight": int, "total_completed": int, "total_failed": int},
            ...
          }
        }
        ```

        The endpoint is always available — when the [fleetq] extra is
        absent the import fails and the response is the canonical
        empty shape (zero counters across the board).
        """
        try:
            from harbormaster.fleetq import get_dispatcher_stats
        except ImportError:
            return {
                "running": [],
                "active_workers": 0,
                "queue_depth": 0,
                "last_dispatched_at": None,
                "tools": {},
            }
        return get_dispatcher_stats().snapshot()

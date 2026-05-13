"""Network UI surface (v10+).

Extracted from ``routes.py`` in v23.0.0a3 — second step of the
routes split. Six endpoints:

  GET /network                                   HTML graph + tabs
  GET /api/network/events                        list with filters
  GET /api/network/events/{event_id}/full        single-event full body
  GET /api/network/stats                         aggregate over window
  GET /api/network/sources                       distinct caller values
  GET /api/network/stream                        SSE push

All six share the ``harbormaster.ui.network_log.network_log`` module
as the data source. Same callable-seam pattern as v23.0.0a1's
``routes_jobs.py`` — pass the ``_render`` closure for HTML routes.
"""
from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator, Callable
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from sse_starlette.sse import EventSourceResponse

from harbormaster.config import HarbormasterConfig

RenderFn = Callable[[Request, str, dict[str, Any]], HTMLResponse]


def register_network_routes(
    app: FastAPI, config: HarbormasterConfig, render: RenderFn,
) -> None:
    """Wire the /network + /api/network/* endpoints onto ``app``."""

    @app.get("/network", response_class=HTMLResponse)
    async def network_page(request: Request) -> HTMLResponse:
        """v10.0.0a7: inter-project network graph view.

        Renders Cytoscape from the vendored `/static/vendor/cytoscape.min.js`
        and feeds it the recent MCP-call events from the in-process
        ring buffer (see `harbormaster.ui.network_log`). New events
        stream in via `/api/network/stream` SSE.
        """
        return render(request, "network.html", {})

    @app.get("/api/network/events")
    async def list_network_events(
        limit: int = 500,
        tool: str | None = None,
        source: str | None = None,
        from_: int | None = Query(None, alias="from"),
        to: int | None = None,
    ) -> dict[str, object]:
        """v13.0.0a4: optional server-side filters.

        - ``?tool=ask_project`` — exact match on the MCP tool name.
        - ``?source=operator`` — exact match on the caller (project
          name for cross-project routing, ``"operator"`` for direct
          dashboard / API use).
        - ``?from=<unix_ms>`` / ``?to=<unix_ms>`` — inclusive
          timestamp range. Either bound is optional.

        All filters AND together. Omitting all four preserves the
        v10/v11/v12 behavior. Filters apply BEFORE LIMIT so the
        operator gets the most recent N matching events, not the
        most recent N events possibly filtered to nothing.
        """
        from harbormaster.ui.network_log import network_log

        if limit < 1 or limit > 5000:
            raise HTTPException(400, "limit must be between 1 and 5000")
        if from_ is not None and to is not None and from_ > to:
            raise HTTPException(400, "from must be <= to")
        events = network_log.recent(
            limit=limit, tool=tool, source=source,
            from_ms=from_, to_ms=to,
        )
        return {
            "count": len(events),
            "events": [e.as_dict() for e in events],
            "filters": {
                "tool": tool,
                "source": source,
                "from": from_,
                "to": to,
            },
        }

    @app.get("/api/network/events/{event_id}/full")
    async def get_network_event_full(event_id: int) -> dict[str, object]:
        """v21.0.8: fetch the untrimmed request body for one ``mcp_calls``
        row. Used by the dashboard chat tab to lazy-load the full
        prompt when the operator expands a row (the list endpoint above
        only ships ``question_preview`` — the 200-char cap stays in
        place to keep the list payload small).

        Returns ``{event_id, question_full, question_preview}`` where
        ``question_full`` is ``null`` for rows recorded before
        v21.0.8 (the column existed but wasn't populated by any
        call site). 404 on unknown ``event_id``.
        """
        from harbormaster.ui.network_log import network_log

        row = network_log.get_full(event_id)
        if row is None:
            raise HTTPException(404, f"event {event_id} not found")
        return {
            "event_id": event_id,
            "question_full": row["question_full"],
            "question_preview": row["question_preview"],
        }

    @app.get("/api/network/stats")
    async def network_stats(window: str = "24h") -> dict[str, object]:
        """v11.0.0a6: aggregate metrics over the last 1h / 24h / 7d.

        Query param `window` accepts: ``1h``, ``24h``, ``7d``, ``all``
        (default ``24h``). Returns total_calls, by_tool counts, top
        5 target projects by call count, and the error rate.
        """
        from harbormaster.ui.network_log import network_log

        windows_ms: dict[str, int | None] = {
            "1h": 60 * 60 * 1000,
            "24h": 24 * 60 * 60 * 1000,
            "7d": 7 * 24 * 60 * 60 * 1000,
            "all": None,
        }
        if window not in windows_ms:
            raise HTTPException(
                400, "window must be one of: 1h, 24h, 7d, all",
            )
        delta = windows_ms[window]
        since_ms: int | None = None
        if delta is not None:
            since_ms = int(time.time() * 1000) - delta
        stats = network_log.stats(since_ms=since_ms)
        return {"window": window, **stats}

    @app.get("/api/network/sources")
    async def network_sources(
        scan_limit: int = 1000,
    ) -> dict[str, list[str]]:
        """v14.0.0a2: distinct caller (source) values from the most
        recent ``scan_limit`` events. Replaces the previously-hardcoded
        source dropdown options on the /network page so the operator
        only ever sees real values.
        """
        from harbormaster.ui.network_log import network_log

        if scan_limit <= 0 or scan_limit > 10_000:
            raise HTTPException(
                400, "scan_limit must be between 1 and 10000",
            )
        return {"sources": network_log.distinct_sources(scan_limit=scan_limit)}

    @app.get("/api/network/stream")
    async def stream_network_events() -> EventSourceResponse:
        """SSE stream of new MCPCallLog events as they're recorded.

        Subscribers receive an `event: event` frame per new entry
        plus a periodic heartbeat so intermediate proxies don't
        idle-time-out the connection.

        v11.0.0a7: heartbeat cadence configurable via
        ``[server] heartbeat_interval_network_s``. Default 30s
        (events are infrequent, frequent heartbeats are pure noise).
        """
        from harbormaster.ui.network_log import network_log

        heartbeat_s = config.server.heartbeat_interval_network_s

        async def gen() -> AsyncIterator[dict[str, str]]:
            queue = network_log.subscribe()
            try:
                while True:
                    try:
                        ev = await asyncio.wait_for(
                            queue.get(), timeout=heartbeat_s,
                        )
                    except TimeoutError:
                        yield {"event": "heartbeat", "data": "{}"}
                        continue
                    yield {
                        "event": "event",
                        "data": json.dumps(ev.as_dict()),
                    }
            finally:
                network_log.unsubscribe(queue)

        return EventSourceResponse(gen())

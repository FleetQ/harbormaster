"""HTTP route handlers for the Live UI + MCP HTTP-direct endpoint.

Endpoints:
  GET  /              dashboard HTML (HTMX + Alpine + Tailwind via CDN)
  GET  /api/health    {"status":"ok", "version":"..."} — UI liveness probe
  GET  /api/projects  JSON list of discovered projects (rich ProjectInfo)
  GET  /health        FleetQ Bridge ping target (alias of /api/health)
  GET  /discover      FleetQ Bridge HTTP-tunnel-mode validation endpoint
  POST /mcp/{server}  HTTP-direct MCP routing — accepts {request_id, method,
                      params, timeout}; dispatches to the FastMCP tool registry
                      passed into create_app(config, mcp=...). 404 when mcp is
                      None or {server} is not 'harbormaster'. When the request
                      sends `Accept: text/event-stream`, the response is an
                      SSE stream of {heartbeat, result | error} events instead
                      of a single JSON document — see _stream_dispatch.

NOTE on imports: FastAPI / Jinja2 are imported eagerly at module top so
the route function annotations resolve via module globals. (PEP 563
future-annotations + lazy imports + FastAPI's get_type_hints don't mix.)
This module is only loaded when the [ui] extra is installed — pure stdio
users never hit this import path.
"""
import asyncio
import json
import time
from collections.abc import AsyncIterator
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from harbormaster import __version__
from harbormaster.config import HarbormasterConfig
from harbormaster.projects import discover_projects

# Heartbeat cadence for SSE streams. Module-level so tests can monkeypatch
# it down to keep the suite fast. Production value is 5s — short enough to
# beat the typical 60s nginx / Cloudflare idle-read timeout, long enough
# that a fast-finishing tool sees zero heartbeat overhead.
_HEARTBEAT_INTERVAL_S: float = 5.0


class McpProxyRequest(BaseModel):
    """Body schema for POST /mcp/{server} — mirrors agent-fleet's
    BridgeController::mcpCall validate() shape."""

    request_id: str | None = None
    method: str = Field(pattern="^(tools/call|tools/list)$")
    params: dict[str, Any] = Field(default_factory=dict)
    timeout: int | None = None


def register_routes(
    app: FastAPI,
    templates: Jinja2Templates,
    config: HarbormasterConfig,
    *,
    mcp: Any | None = None,
) -> None:
    @app.get("/", response_class=HTMLResponse)
    async def dashboard(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(
            request,
            "dashboard.html",
            {"version": __version__},
        )

    @app.get("/api/health")
    async def api_health() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    @app.get("/api/projects")
    async def list_projects() -> list[dict[str, object]]:
        return [p.as_dict() for p in discover_projects(config.projects)]

    @app.get("/health")
    async def fleetq_health() -> dict[str, str]:
        """Alias of /api/health using the path FleetQ Bridge expects when
        pinging an HTTP-tunnel-mode connection."""
        return {"status": "ok", "version": __version__}

    @app.get("/discover")
    async def fleetq_discover() -> dict[str, object]:
        """FleetQ Bridge HTTP-tunnel-mode validation endpoint."""
        try:
            from harbormaster.fleetq import build_manifest
        except ImportError:
            return {"agents": [], "llm_endpoints": [], "mcp_servers": []}
        return build_manifest()

    @app.post("/mcp/{server}")
    async def mcp_proxy(
        server: str,
        body: McpProxyRequest,
        request: Request,
    ) -> Any:
        """HTTP-direct MCP routing (FleetQ HTTP-tunnel-mode receive side).

        Accepts the same payload shape as agent-fleet's BridgeController::mcpCall
        validate() block: {request_id?, method, params, timeout?}. Looks up the
        named tool in the FastMCP tool registry (passed into create_app via
        the `mcp` kwarg) and returns an MCP-style result envelope.

        Streaming: when the client sends `Accept: text/event-stream`, the
        response is an SSE stream that emits periodic `heartbeat` events
        while the tool runs (so reverse proxies don't time out long calls
        like ask_project / delegate_task / fan_out_ask) and a final
        `result` (or `error`) event with the same envelope JSON-mode would
        return. JSON mode (default Accept) is fully unchanged.

        404 when:
          - {server} != 'harbormaster'
          - create_app was called without an mcp instance (UI-only mode)
        """
        if server != "harbormaster":
            raise HTTPException(404, f"unknown MCP server: {server!r}")
        if mcp is None:
            raise HTTPException(
                404,
                "MCP HTTP-direct routing not available — harbormaster-ui was "
                "started without an MCP server bound. Run harbormaster-mcp "
                "alongside, or update your launcher to pass mcp=build_server(config).",
            )

        accept = request.headers.get("accept", "")
        if "text/event-stream" in accept.lower():
            return EventSourceResponse(_stream_dispatch(mcp, body))

        return _dispatch_mcp(mcp, body)


async def _stream_dispatch(
    mcp: Any, body: McpProxyRequest
) -> AsyncIterator[dict[str, str]]:
    """SSE event generator for the streaming `/mcp/{server}` path.

    The current MCP tool dispatch is synchronous — once a tool starts, it
    runs to completion before yielding a value. We therefore can't emit
    real token-by-token chunks here yet; what we *can* do is emit a
    `heartbeat` event every `_HEARTBEAT_INTERVAL_S` seconds so the wire
    stays warm through long-running tools (ask_project, delegate_task,
    fan_out_ask), then emit the final envelope as a `result` or `error`
    event.

    Event shapes (data is JSON-encoded for every event):
      heartbeat → {"elapsed_ms": <int>}
      result    → <MCP envelope, identical to JSON-mode response body>
      error     → {"status": <int>, "detail": <str>}

    Future direction: once tools expose AsyncIterator-based streaming
    (e.g. ask_project pipes Claude tokens), this generator will yield
    `chunk` events between the heartbeats. The current shape is forward-
    compatible — callers that already handle `chunk` events get nothing
    today, callers that don't are unaffected.
    """
    start = time.monotonic()
    task = asyncio.create_task(asyncio.to_thread(_dispatch_mcp, mcp, body))

    while not task.done():
        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=_HEARTBEAT_INTERVAL_S)
        except TimeoutError:
            elapsed_ms = int((time.monotonic() - start) * 1000)
            yield {
                "event": "heartbeat",
                "data": json.dumps({"elapsed_ms": elapsed_ms}),
            }
        except BaseException:  # noqa: BLE001 — task raised, post-loop handles it
            # When the wrapped task raises, wait_for re-raises here. We
            # break out of the heartbeat loop and let the post-loop
            # `task.result()` re-raise into our error handlers, which
            # render the failure as an in-band SSE event instead of
            # propagating up Starlette's exception middleware (which
            # would try to send a fresh response on a stream that has
            # already started).
            break

    try:
        result = task.result()
    except HTTPException as e:
        yield {
            "event": "error",
            "data": json.dumps({"status": e.status_code, "detail": e.detail}),
        }
        return
    except Exception as e:  # noqa: BLE001 — surface any error as SSE event
        yield {
            "event": "error",
            "data": json.dumps(
                {"status": 500, "detail": f"{type(e).__name__}: {e}"}
            ),
        }
        return

    yield {"event": "result", "data": json.dumps(result)}


def _dispatch_mcp(mcp: Any, body: McpProxyRequest) -> dict[str, Any]:
    """Translate body.method + body.params into a tool call against
    FastMCP's tool manager and return an MCP JSON-RPC-shaped response."""
    if body.method == "tools/list":
        return {
            "result": {
                "tools": [
                    {
                        "name": t.name,
                        "description": getattr(t, "description", "") or "",
                    }
                    for t in mcp._tool_manager.list_tools()
                ]
            }
        }

    # tools/call
    name = body.params.get("name")
    if not isinstance(name, str) or not name:
        raise HTTPException(400, "params.name (string) is required for tools/call")
    arguments = body.params.get("arguments") or {}
    if not isinstance(arguments, dict):
        raise HTTPException(400, "params.arguments must be an object")

    tool = next(
        (t for t in mcp._tool_manager.list_tools() if t.name == name),
        None,
    )
    if tool is None:
        raise HTTPException(404, f"tool not found: {name!r}")

    try:
        result = tool.fn(**arguments)
    except TypeError as e:
        raise HTTPException(400, f"tool argument error: {e}") from e
    except Exception as e:  # noqa: BLE001 - propagate as MCP error envelope
        return {
            "result": {
                "isError": True,
                "content": [
                    {"type": "text", "text": f"{type(e).__name__}: {e}"}
                ],
            }
        }

    return {"result": {"content": [_serialize_tool_result(result)]}}


def _serialize_tool_result(result: Any) -> dict[str, Any]:
    """MCP tool results land as `content` entries — text for strings, JSON
    serialization for everything else."""
    if isinstance(result, str):
        return {"type": "text", "text": result}
    try:
        return {"type": "text", "text": json.dumps(result, default=str)}
    except (TypeError, ValueError):
        return {"type": "text", "text": str(result)}

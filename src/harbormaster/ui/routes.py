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
                      None or {server} is not 'harbormaster'.

NOTE on imports: FastAPI / Jinja2 are imported eagerly at module top so
the route function annotations resolve via module globals. (PEP 563
future-annotations + lazy imports + FastAPI's get_type_hints don't mix.)
This module is only loaded when the [ui] extra is installed — pure stdio
users never hit this import path.
"""
import json
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from harbormaster import __version__
from harbormaster.config import HarbormasterConfig
from harbormaster.projects import discover_projects


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
    async def mcp_proxy(server: str, body: McpProxyRequest) -> dict[str, Any]:
        """HTTP-direct MCP routing (FleetQ HTTP-tunnel-mode receive side).

        Accepts the same payload shape as agent-fleet's BridgeController::mcpCall
        validate() block: {request_id?, method, params, timeout?}. Looks up the
        named tool in the FastMCP tool registry (passed into create_app via
        the `mcp` kwarg) and returns an MCP-style result envelope.

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
        return _dispatch_mcp(mcp, body)


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

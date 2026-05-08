"""HTTP route handlers for the Live UI.

Endpoints (v1.0.0a7):
  GET  /              dashboard HTML (HTMX + Alpine + Tailwind via CDN)
  GET  /api/health    {"status":"ok", "version":"..."} — UI liveness probe
  GET  /api/projects  JSON list of discovered projects (rich ProjectInfo)
  GET  /health        same shape as /api/health — FleetQ Bridge ping target
  GET  /discover      FleetQ Bridge HTTP-tunnel mode validation endpoint;
                      returns the same {agents, llm_endpoints, mcp_servers}
                      manifest as register sends, sourced from the same
                      harbormaster.fleetq.endpoints.build_manifest() function.

SSE stream of in-flight queries lands in v1.0.0a8+ once the MCP-side
event broadcast plumbing is in place.

NOTE on imports: FastAPI / Jinja2 are imported eagerly at module top so
the route function annotations resolve via module globals. (PEP 563
future-annotations + lazy imports + FastAPI's get_type_hints don't mix.)
This module is only loaded when the [ui] extra is installed — pure stdio
users never hit this import path.
"""
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from harbormaster import __version__
from harbormaster.config import HarbormasterConfig
from harbormaster.projects import discover_projects


def register_routes(
    app: FastAPI,
    templates: Jinja2Templates,
    config: HarbormasterConfig,
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
        """FleetQ Bridge HTTP-tunnel-mode validation endpoint.

        Called once when the user pastes a tunnel URL into FleetQ's "Connect
        a bridge" form. FleetQ stores the returned manifest as the connection's
        endpoints. Subsequent MCP calls go through whichever transport FleetQ
        uses (currently the WebSocket relay path; an HTTP-direct path may
        land in future agent-fleet versions).

        Auth: harbormaster-ui's bearer middleware enforces the same
        HARBORMASTER_UI_TOKEN that FleetQ sends as `endpoint_secret`.
        """
        # Deferred import keeps the [fleetq] extra optional. If the user runs
        # harbormaster-ui without [fleetq], they don't get the FleetQ-flavored
        # manifest — the endpoint reports an empty manifest instead so probes
        # still get a 200 instead of a 500.
        try:
            from harbormaster.fleetq import build_manifest
        except ImportError:
            return {"agents": [], "llm_endpoints": [], "mcp_servers": []}
        return build_manifest()

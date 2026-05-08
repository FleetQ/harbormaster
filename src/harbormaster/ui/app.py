"""FastAPI app factory for the Live UI.

NOTE: this module is only imported when the [ui] extra is present (the
parent harbormaster.ui __init__.py is the gatekeeper). Eager imports of
FastAPI / Starlette here are fine — stdio MCP users never load this path.
"""
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.templating import Jinja2Templates

from harbormaster import __version__
from harbormaster.config import HarbormasterConfig
from harbormaster.ui.routes import register_routes

UI_DIR = Path(__file__).parent
TEMPLATES_DIR = UI_DIR / "templates"


def create_app(config: HarbormasterConfig, *, mcp: Any | None = None) -> FastAPI:
    """Build the FastAPI app wired against the given Harbormaster config.

    When `mcp` (a FastMCP instance from harbormaster.server.build_server) is
    provided, the POST /mcp/{server} HTTP-direct routing endpoint is wired up
    so FleetQ HTTP-tunnel-mode bridges (and any other HTTP MCP client) can
    proxy tool calls into harbormaster's tool registry without needing the
    WebSocket relay path. `mcp=None` keeps the UI usable on its own as a
    project dashboard without exposing the proxy endpoint.
    """
    app = FastAPI(
        title="Harbormaster",
        version=__version__,
        description="Live UI for the Harbormaster MCP server.",
    )

    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
    register_routes(app, templates, config, mcp=mcp)
    return app

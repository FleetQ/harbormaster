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


def create_app(
    config: HarbormasterConfig,
    *,
    mcp: Any | None = None,
    auth_token: str | None = None,
) -> FastAPI:
    """Build the FastAPI app wired against the given Harbormaster config.

    When `mcp` (a FastMCP instance from harbormaster.server.build_server) is
    provided, the POST /mcp/{server} HTTP-direct routing endpoint is wired up
    so FleetQ HTTP-tunnel-mode bridges (and any other HTTP MCP client) can
    proxy tool calls into harbormaster's tool registry without needing the
    WebSocket relay path. `mcp=None` keeps the UI usable on its own as a
    project dashboard without exposing the proxy endpoint.

    When `auth_token` is non-empty, the value is propagated into every
    rendered template's context (v3.0.0a6) so client-side `hmFetch()`
    can inject `Authorization: Bearer <token>` on every SSE / API call
    that the dashboard's forms make. Pass `None` (default) when the UI
    runs unauthenticated (loopback + no env token); the meta tag is
    omitted in that case.
    """
    app = FastAPI(
        title="Harbormaster",
        version=__version__,
        description="Live UI for the Harbormaster MCP server.",
    )

    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
    # v7.0.0a6: register the language_badge filter so dashboard.html
    # can render `{{ project.language | language_badge }}`.
    from harbormaster.ui.manifest_cache import language_badge_class

    templates.env.filters["language_badge"] = language_badge_class
    # v12.0.0a3: apply operator-configured retention caps to the
    # module-level singleton stores. Defaults match the v11
    # hard-coded values, so this is a no-op when the operator hasn't
    # set [retention] in their config.
    from harbormaster.ui.memory_revisions import memory_revisions
    from harbormaster.ui.network_log import network_log

    network_log.set_max_rows(config.retention.network_log_max_rows)
    memory_revisions.set_max_per_file(config.retention.memory_revisions_per_file)
    register_routes(app, templates, config, mcp=mcp, auth_token=auth_token)
    return app

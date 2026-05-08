"""FastAPI app factory for the Live UI.

NOTE: this module is only imported when the [ui] extra is present (the
parent harbormaster.ui __init__.py is the gatekeeper). Eager imports of
FastAPI / Starlette here are fine — stdio MCP users never load this path.
"""
from pathlib import Path

from fastapi import FastAPI
from fastapi.templating import Jinja2Templates

from harbormaster import __version__
from harbormaster.config import HarbormasterConfig
from harbormaster.ui.routes import register_routes

UI_DIR = Path(__file__).parent
TEMPLATES_DIR = UI_DIR / "templates"


def create_app(config: HarbormasterConfig) -> FastAPI:
    """Build the FastAPI app wired against the given Harbormaster config.

    No /static mount in v1.0.0a5 — every CSS/JS asset is CDN-loaded via
    the base.html template. When v1.0.0a6+ ships local assets we'll
    re-add the mount and a real `static/` dir at the same time.
    """
    app = FastAPI(
        title="Harbormaster",
        version=__version__,
        description="Live UI for the Harbormaster MCP server.",
    )

    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
    register_routes(app, templates, config)
    return app

"""FastAPI app factory for the Live UI.

NOTE: this module is only imported when the [ui] extra is present (the
parent harbormaster.ui __init__.py is the gatekeeper). Eager imports of
FastAPI / Starlette here are fine — stdio MCP users never load this path.
"""
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from harbormaster import __version__
from harbormaster.config import HarbormasterConfig
from harbormaster.ui.routes import register_routes

UI_DIR = Path(__file__).parent
TEMPLATES_DIR = UI_DIR / "templates"
STATIC_DIR = UI_DIR / "static"


def create_app(config: HarbormasterConfig) -> FastAPI:
    """Build the FastAPI app wired against the given Harbormaster config."""
    app = FastAPI(
        title="Harbormaster",
        version=__version__,
        description="Live UI for the Harbormaster MCP server.",
    )

    if STATIC_DIR.is_dir():
        app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
    register_routes(app, templates, config)
    return app

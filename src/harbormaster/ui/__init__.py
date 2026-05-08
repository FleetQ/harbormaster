"""Harbormaster Live UI — FastAPI dashboard.

Optional dependency stack: shipped behind the `[ui]` extra so stdio MCP
users don't pay the FastAPI / uvicorn / Jinja2 install cost. Activate via
`pip install harbormaster-mcp[ui]` and run `harbormaster-ui`.
"""
from harbormaster.ui.app import create_app

__all__ = ["create_app"]

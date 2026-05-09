"""Example Harbormaster plugin.

Registers a single MCP tool, `greet_project`, that returns a hardcoded
greeting for any project name. Use this as a template for shipping
additional MCP tools alongside Harbormaster's built-ins.

Wiring: in your distribution's `pyproject.toml`:

    [project.entry-points."harbormaster.tools"]
    hello = "harbormaster_plugin_hello:register"

Then in the operator's `harbormaster.toml`:

    [plugins]
    enabled = true
    allow = ["harbormaster-plugin-hello"]

The plugin's `register()` is invoked at server startup with the same
`(mcp, config)` arguments built-in tools receive.
"""
from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from harbormaster.config import HarbormasterConfig


def register(mcp: FastMCP, config: HarbormasterConfig) -> None:
    @mcp.tool()
    def greet_project(name: str) -> str:
        """Return a friendly greeting for the named project.

        Demonstrates the minimum plugin contract — same shape as
        Harbormaster's built-in `register_*` functions.
        """
        return f"Hello, {name}! Greetings from harbormaster-plugin-hello."

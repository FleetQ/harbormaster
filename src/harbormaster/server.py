"""FastMCP server bootstrap and tool registration."""
from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from harbormaster.config import HarbormasterConfig
from harbormaster.tools import register_tools


def build_server(config: HarbormasterConfig) -> FastMCP:
    """Construct the MCP server with every tool wired against the loaded config."""
    mcp = FastMCP("harbormaster")
    register_tools(mcp, config)
    return mcp

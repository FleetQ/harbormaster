"""MCP tool registration. `register_tools(mcp, config)` wires every tool against
the loaded config so they share project discovery, backend choice, and SSH hosts."""
from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from harbormaster.config import HarbormasterConfig
from harbormaster.tools.ask import register as register_ask
from harbormaster.tools.delegate import register as register_delegate
from harbormaster.tools.fan_out import register as register_fan_out
from harbormaster.tools.hosts import register as register_hosts
from harbormaster.tools.projects import register as register_projects


def register_tools(mcp: FastMCP, config: HarbormasterConfig) -> None:
    register_projects(mcp, config)
    register_ask(mcp, config)
    register_delegate(mcp, config)
    register_fan_out(mcp, config)
    register_hosts(mcp, config)


__all__ = ["register_tools"]

"""MCP tool registration. `register_tools(mcp, config)` wires every tool against
the loaded config so they share project discovery, backend choice, and SSH hosts."""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from harbormaster.config import HarbormasterConfig
from harbormaster.plugins import load_plugins
from harbormaster.tools.ask import register as register_ask
from harbormaster.tools.await_jobs import register as register_await_jobs
from harbormaster.tools.clarify import register as register_clarify
from harbormaster.tools.delegate import register as register_delegate
from harbormaster.tools.fan_out import register as register_fan_out
from harbormaster.tools.graph import register as register_graph
from harbormaster.tools.hosts import register as register_hosts
from harbormaster.tools.inbox import register as register_inbox
from harbormaster.tools.job_resources import register as register_job_resources
from harbormaster.tools.job_status import register as register_job_status
from harbormaster.tools.projects import register as register_projects
from harbormaster.tools.recall import register as register_recall


def register_tools(mcp: FastMCP, config: HarbormasterConfig) -> None:
    # Built-in tools first; plugins land last so they can complement
    # (but never override) the built-in surface.
    register_projects(mcp, config)
    register_ask(mcp, config)
    register_delegate(mcp, config)
    register_fan_out(mcp, config)
    register_hosts(mcp, config)
    register_recall(mcp, config)
    register_graph(mcp, config)
    register_job_status(mcp, config)
    register_inbox(mcp, config)
    register_await_jobs(mcp, config)
    register_clarify(mcp, config)
    register_job_resources(mcp, config)

    # v2.0.0a4: opt-in entry-point plugin discovery. No-op (with a
    # single debug log) when [plugins].enabled is false.
    load_plugins(mcp, config)


__all__ = ["register_tools"]

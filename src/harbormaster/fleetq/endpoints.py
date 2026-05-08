"""FleetQ Bridge endpoints manifest — single source of truth.

The manifest sent in `POST /api/v1/bridge/register` and returned from the
HTTP-tunnel-mode `GET /discover` endpoint share the same wire shape. This
module owns that shape so both callers stay in lockstep.
"""
from __future__ import annotations

from typing import Any

# v1.0.0a7 ships only the harbormaster MCP server itself. Future versions
# may discover and announce other local MCP servers, agents, LLMs.
HARBORMASTER_TOOLS: list[str] = [
    "list_projects",
    "list_hosts",
    "project_status",
    "ask_project",
    "delegate_task",
    "fan_out_ask",
]


def build_manifest() -> dict[str, Any]:
    """Return the canonical endpoints manifest for harbormaster.

    Shape matches FleetQ's expected dict:
      {
        "agents": [],
        "llm_endpoints": [],
        "mcp_servers": [{"name": ..., "description": ..., "tools": [...]}]
      }

    Stable across the wire; do not change keys without bumping the
    bridge_version + verifying agent-fleet compatibility.
    """
    return {
        "agents": [],
        "llm_endpoints": [],
        "mcp_servers": [{
            "name": "harbormaster",
            "description": (
                "Project-router MCP — list_projects, project_status, ask_project, "
                "delegate_task, fan_out_ask, list_hosts."
            ),
            "tools": list(HARBORMASTER_TOOLS),
        }],
    }

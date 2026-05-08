"""list_hosts MCP tool — merge configured [hosts] with ~/.ssh/config aliases."""
from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from harbormaster.config import HarbormasterConfig
from harbormaster.ssh import list_ssh_hosts


def register(mcp: FastMCP, config: HarbormasterConfig) -> None:
    @mcp.tool()
    def list_hosts() -> list[str]:
        """List host aliases from harbormaster config and ~/.ssh/config.

        Configured `[hosts.<name>]` entries take precedence (returned first).
        Wildcard ssh_config Hosts (containing '*' or '?') are filtered out.
        """
        from_ssh = list_ssh_hosts()
        from_config = list(config.hosts.keys())
        seen: set[str] = set()
        result: list[str] = []
        for h in from_config + from_ssh:
            if h in seen:
                continue
            seen.add(h)
            result.append(h)
        return result

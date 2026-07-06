"""FastMCP server bootstrap and tool registration."""
from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from harbormaster.config import HarbormasterConfig
from harbormaster.tools import register_tools

# Server-level instructions surfaced to the calling MCP client once per session.
# Keep it tight — it is injected into the client's context. Orients the model on
# the delegate→await workflow and, critically, on the long-poll timeout pitfall
# that bites interactive clients (Claude Desktop / claude.ai) where a tool call
# can only stay open for a few minutes before its result window expires.
SERVER_INSTRUCTIONS = """\
Harbormaster routes Q&A and delegates work across your local projects (~/htdocs/*)
and configured SSH hosts. Each project answers with its own CLAUDE.md + memories loaded.

Core workflow:
- `ask_project` / `fan_out_ask` — quick synchronous questions about one or many projects.
- `delegate_task` — hand a project a real unit of work; returns a job_id and runs async.
- Collect results with `await_delegated_task(job_id)` (one job) or `await_inbox(inbox_id)`
  (any completion), then `recall_pending_results(..., mark_read=true)` to consume them.
- `recall_qa` — search prior answers before re-asking.

Long-poll timeouts (IMPORTANT): `await_delegated_task` and `await_inbox` block up to
`timeout_seconds` (default 900). Interactive clients (Claude Desktop, claude.ai) can hold a
tool call open only for a few minutes before the tool-result window expires and the call
fails with "request may have expired". On those clients pass a SHORT `timeout_seconds`
(60-120) and re-call to keep waiting — do NOT rely on the 900s default, which is meant for
unattended runners (Claude Code) that can hold a request open. `timed_out: true` /
status `queued`|`running` just means "nothing yet" — re-call, it is not an error.
"""


def build_server(config: HarbormasterConfig) -> FastMCP:
    """Construct the MCP server with every tool wired against the loaded config."""
    mcp = FastMCP("harbormaster", instructions=SERVER_INSTRUCTIONS)
    register_tools(mcp, config)
    return mcp

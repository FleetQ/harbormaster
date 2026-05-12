"""``recall_pending_results`` MCP tool (v22.0.0a3).

The inbox half of the async delegate flow. Agent A calls
``delegate_task(..., mode="async", inbox_id="<name>")`` to enqueue
work, then later calls ``recall_pending_results(inbox_id="<name>")``
to fetch every completed / failed job in that inbox at once.

By default, fetched jobs are immediately marked read so they do not
re-appear on the next poll. Pass ``mark_read=False`` to peek without
consuming the inbox (useful for UIs / debugging).

Identity model is the simplest possible: a free-form string. Any
caller in the same MCP process can read any inbox. Suits the local
threat model — for cross-machine / multi-tenant inbox isolation,
revisit in v23.
"""
from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from harbormaster.config import HarbormasterConfig


def register(mcp: FastMCP, config: HarbormasterConfig) -> None:
    @mcp.tool()
    def recall_pending_results(
        inbox_id: str = "default",
        mark_read: bool = True,
        limit: int = 50,
    ) -> dict[str, Any]:
        """Fetch completed / failed async delegate jobs from an inbox.

        Returns ``{"inbox_id": "...", "results": [<job dict>, ...],
        "marked_read": <int>}``. ``results`` is sorted by
        ``completed_at`` ascending (oldest first) so a polling agent
        processes jobs in the order they finished.

        ``mark_read=True`` (default) sets ``read_at`` on every
        returned row so subsequent polls skip them. ``mark_read=False``
        peeks without consuming the inbox.

        ``limit`` caps the batch size. Caller polls again if more
        remain (the inbox is FIFO; repeated polls drain it in order).
        """
        from harbormaster.jobs import get_subsystem
        sub = get_subsystem(config)
        jobs = sub.store.list_pending_for_inbox(inbox_id, limit=limit)
        results = [j.as_dict() for j in jobs]
        marked = 0
        if mark_read and jobs:
            marked = sub.store.mark_read([j.id for j in jobs])
        return {
            "inbox_id": inbox_id,
            "results": results,
            "marked_read": marked,
        }

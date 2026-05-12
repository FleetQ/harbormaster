"""``get_delegated_task`` MCP tool (v22.0.0a2).

Returns the current status of an async delegate job — the polling
half of the inbox flow. Agent A holds the ``job_id`` returned by
``delegate_task(..., mode="async")`` and calls this tool periodically
until ``status`` is ``"completed"`` or ``"failed"``.
"""
from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from harbormaster.config import HarbormasterConfig


def register(mcp: FastMCP, config: HarbormasterConfig) -> None:
    @mcp.tool()
    def get_delegated_task(job_id: str) -> dict[str, Any]:
        """Return the status of an async delegated job.

        ``status`` is one of ``"queued"``, ``"running"``, ``"completed"``,
        ``"failed"``. ``output`` carries the subagent's markdown summary
        when ``status == "completed"``; ``error`` carries the
        ``"Error: ..."`` string and ``cid`` correlation id when
        ``status == "failed"``.

        Returns ``{"error": "not_found", "job_id": <id>}`` if the id
        does not match any row — distinguishable from a real backend
        failure by the absence of ``status``.
        """
        from harbormaster.jobs import get_subsystem
        sub = get_subsystem(config)
        job = sub.store.get(job_id)
        if job is None:
            return {"error": "not_found", "job_id": job_id}
        return job.as_dict()

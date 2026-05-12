"""MCP resource exposure for delegated jobs (v22.2.0).

Each delegated job is queryable as a parametrised MCP resource:

  - ``harbormaster://jobs/recent`` — top 50 rows (newest first)
  - ``harbormaster://jobs/{job_id}`` — one job's full payload

Clients with resource-list support can enumerate jobs and read them
without going through the tool layer. Clients that additionally
support ``resources/subscribe`` could in theory get push notifications
on updates — wiring exists on the JobStore side via ``add_subscriber``
(v22.1.0) but FastMCP's current subscription forwarding is
client-implementation-dependent, so this side is best-effort.

The SSE stream at ``GET /api/delegated-jobs/stream`` (v22.2.0) is the
authoritative push channel for non-MCP consumers (dashboards,
webhooks, external observers).
"""
from __future__ import annotations

import json
from typing import Any

from mcp.server.fastmcp import FastMCP

from harbormaster.config import HarbormasterConfig


def register(mcp: FastMCP, config: HarbormasterConfig) -> None:
    @mcp.resource("harbormaster://jobs/recent")
    def jobs_recent() -> str:
        """Recent delegated jobs (top 50, newest first) as a JSON
        array of ``Job.as_dict()`` objects."""
        from harbormaster.jobs import get_subsystem

        sub = get_subsystem(config)
        jobs = sub.store.list_recent(limit=50)
        return json.dumps([j.as_dict() for j in jobs])

    @mcp.resource("harbormaster://jobs/{job_id}")
    def job_by_id(job_id: str) -> str:
        """One delegated job as a JSON ``Job.as_dict()`` object.
        Returns ``{"error": "not_found", "job_id": ...}`` if unknown."""
        from harbormaster.jobs import get_subsystem

        sub = get_subsystem(config)
        job = sub.store.get(job_id)
        payload: dict[str, Any] = (
            {"error": "not_found", "job_id": job_id}
            if job is None else job.as_dict()
        )
        return json.dumps(payload)

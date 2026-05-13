"""Delegated Jobs UI surface (v22.0.0a4 + v22.2.0).

Extracted from ``routes.py`` in v23.0.0a1 as the first conservative
step of the long-deferred routes split. Five endpoints:

  GET /jobs                          HTML dashboard
  GET /api/delegated-jobs            list with filters
  GET /api/delegated-jobs/summary    counter strip
  GET /api/delegated-jobs/stream     SSE push (v22.2.0)
  GET /api/delegated-jobs/{job_id}   single-row lazy-fetch

``register_jobs_routes(app, config, render)`` wires them onto the
given FastAPI app. ``render`` is the same ``_render`` closure that
``create_app`` builds — it captures ``templates`` + ``auth_ctx`` +
``base_ctx`` + ``version``. Passing it in keeps this module
independent of ``create_app``'s internals.

Subsequent v23 alphas will extract the network, dispatcher, and
history-admin surfaces using the same shape.
"""
from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator, Callable
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from sse_starlette.sse import EventSourceResponse

from harbormaster.config import HarbormasterConfig
from harbormaster.jobs.schema import (
    STATUS_COMPLETED,
    STATUS_FAILED,
    STATUS_QUEUED,
    STATUS_RUNNING,
    VALID_STATUSES,
)

RenderFn = Callable[[Request, str, dict[str, Any]], HTMLResponse]


def register_jobs_routes(
    app: FastAPI, config: HarbormasterConfig, render: RenderFn,
) -> None:
    """Wire the /jobs + /api/delegated-jobs* endpoints onto ``app``.

    Registration order matches the pre-v23.0.0a1 inline placement
    in ``routes.py`` — caller invokes this between the network
    stream block and the ``/projects/{name}`` route to preserve
    FastAPI's first-match route resolution.
    """

    @app.get("/jobs", response_class=HTMLResponse)
    async def jobs_page(request: Request) -> HTMLResponse:
        """Async delegate jobs dashboard (v22.0.0a4).

        Lists rows from the JobStore with status filter chips. Each
        row expands inline to show the subagent's output / error,
        lazy-fetched per the v21.0.8 pattern. v22.2.0 added SSE
        live-update via /api/delegated-jobs/stream.
        """
        return render(request, "jobs.html", {})

    @app.get("/api/delegated-jobs")
    async def list_delegated_jobs(
        status: str | None = None,
        project: str | None = None,
        limit: int = 200,
    ) -> dict[str, object]:
        """v22.0.0a4: list rows from the async delegate JobStore.

        Filters: ``?status=queued|running|completed|failed`` and
        ``?project=<name>``. ``?limit=<N>`` caps the batch (1..1000).
        Output is sorted by ``queued_at`` DESC — newest first.
        """
        from harbormaster.jobs import get_subsystem

        if limit < 1 or limit > 1000:
            raise HTTPException(400, "limit must be between 1 and 1000")
        if status is not None and status not in VALID_STATUSES:
            raise HTTPException(400, f"status must be one of {sorted(VALID_STATUSES)}")

        sub = get_subsystem(config)
        jobs = await asyncio.to_thread(
            sub.store.list_recent,
            project=project, status=status, limit=limit,
        )
        return {
            "count": len(jobs),
            "jobs": [j.as_dict() for j in jobs],
            "filters": {"status": status, "project": project},
        }

    @app.get("/api/delegated-jobs/summary")
    async def delegated_jobs_summary() -> dict[str, int]:
        """v22.0.0a4: counts for the dashboard counter.

        Returns ``{queued, running, completed_today, failed_today}``
        where the ``_today`` keys count rows that completed in the
        last 24h regardless of inbox. ``queued`` + ``running`` are
        process-wide point-in-time counts.
        """
        from harbormaster.jobs import get_subsystem

        sub = get_subsystem(config)
        cutoff = time.time() - 86400.0

        def _counts() -> dict[str, int]:
            with sub.store._lock:
                rows = sub.store._conn.execute(
                    "SELECT status, COUNT(*) AS c "
                    "FROM delegated_jobs "
                    "WHERE status IN (?, ?) "
                    "   OR (status IN (?, ?) AND completed_at >= ?) "
                    "GROUP BY status",
                    (
                        STATUS_QUEUED, STATUS_RUNNING,
                        STATUS_COMPLETED, STATUS_FAILED, cutoff,
                    ),
                ).fetchall()
            out = {
                "queued": 0, "running": 0,
                "completed_today": 0, "failed_today": 0,
            }
            for row in rows:
                key = {
                    STATUS_QUEUED: "queued",
                    STATUS_RUNNING: "running",
                    STATUS_COMPLETED: "completed_today",
                    STATUS_FAILED: "failed_today",
                }[row["status"]]
                out[key] = row["c"]
            return out

        return await asyncio.to_thread(_counts)

    @app.get("/api/delegated-jobs/stream")
    async def stream_delegated_jobs() -> EventSourceResponse:
        """v22.2.0: SSE stream of job state changes.

        Each completion or failure pushes an ``event: event`` frame
        carrying the full ``Job.as_dict()`` payload. Periodic
        ``event: heartbeat`` frames keep proxies from idle-timing-out
        the connection — same cadence config as the network stream.
        """
        from harbormaster.jobs import get_subsystem

        sub = get_subsystem(config)
        heartbeat_s = config.server.heartbeat_interval_network_s

        async def gen() -> AsyncIterator[dict[str, str]]:
            queue = sub.broadcaster.subscribe()
            try:
                while True:
                    try:
                        ev = await asyncio.wait_for(
                            queue.get(), timeout=heartbeat_s,
                        )
                    except TimeoutError:
                        yield {"event": "heartbeat", "data": "{}"}
                        continue
                    yield {"event": "event", "data": json.dumps(ev)}
            finally:
                sub.broadcaster.unsubscribe(queue)

        return EventSourceResponse(gen())

    @app.get("/api/delegated-jobs/{job_id}")
    async def get_delegated_job(job_id: str) -> dict[str, object]:
        """v22.0.0a4: fetch one job by id. 404 on unknown.

        Returns the same shape the MCP ``get_delegated_task`` tool
        returns (with ``output``, ``error``, etc.). Used by the row
        expand on /jobs.
        """
        from harbormaster.jobs import get_subsystem

        sub = get_subsystem(config)
        job = await asyncio.to_thread(sub.store.get, job_id)
        if job is None:
            raise HTTPException(404, f"job {job_id!r} not found")
        return job.as_dict()

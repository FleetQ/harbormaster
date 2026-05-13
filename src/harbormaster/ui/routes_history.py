"""History admin UI surface (v4+).

Extracted from ``routes.py`` in v23.0.0a5 — fourth and final routes-
split alpha. Six endpoints around the auto-reembed background runner:

  POST /api/history/reembed                     trigger run
  POST /api/history/reembed/cancel              request cancel
  GET  /api/history/state                       runner phase + progress
  GET  /api/history/reembed/runs                rolling log of completed runs
  GET  /api/history/reembed/runs/diff           2-way diff between runs
  GET  /api/history/reembed/runs/compare        N-way comparison (≤4)

All six gate on the ``[history]`` extra being installed. When it's
not, GET endpoints return canonical-empty shapes; POST / mutation
endpoints raise 503.

Stateless — no closure dependencies beyond ``config`` (for the
``auto_reembed_enabled`` flag on `/api/history/state`).
"""
from __future__ import annotations

from fastapi import FastAPI, HTTPException, Query

from harbormaster.config import HarbormasterConfig


def register_history_routes(
    app: FastAPI, config: HarbormasterConfig,
) -> None:
    """Wire the /api/history/* endpoints onto ``app``.

    Note: no ``render`` argument — none of these are HTML routes.
    """

    @app.post("/api/history/reembed")
    async def api_history_reembed_trigger() -> dict[str, object]:
        """v6.0.0a1: manually trigger an auto-reembed run.

        Idempotent: returns 409 when one is already in progress
        (prevents double-click + cross-tab races from spawning
        two threads).
        """
        try:
            from harbormaster.history import trigger_manual_reembed
        except ImportError:
            raise HTTPException(
                503,
                "[history] extra not installed; install with "
                "`pip install harbormaster-mcp[history]`",
            ) from None

        started, error = trigger_manual_reembed(config)
        if not started:
            status = 409 if error and "already in progress" in error else 400
            raise HTTPException(status, error or "could not start reembed")
        return {"started": True}

    @app.get("/api/history/state")
    async def api_history_state() -> dict[str, object]:
        """v4.0.0a5: report the auto-reembed runner's current phase.

        Reads the cross-process state file written by the background
        thread (when ``[history] auto_reembed_on_drift = true``). Returns
        an idle snapshot when the file is absent or the thread never
        started.
        """
        try:
            from harbormaster.history import read_reembed_state

            state = read_reembed_state()
            return {
                "available": True,
                "phase": state.phase,
                "processed": state.processed,
                "total": state.total,
                "current_host": state.current_host,
                "started_at": state.started_at,
                "finished_at": state.finished_at,
                "error": state.error,
                "writer_pid": state.writer_pid,
                "cancel_requested": state.cancel_requested,
                "auto_reembed_enabled": config.history.auto_reembed_on_drift,
            }
        except ImportError:
            return {
                "available": False,
                "phase": "idle",
                "auto_reembed_enabled": False,
            }

    @app.get("/api/history/reembed/runs")
    async def api_history_reembed_runs() -> dict[str, object]:
        """v7.0.0a4: rolling log of completed reembed runs.

        Returns ``{"runs": [...]}`` where each entry is a
        ReembedRunRecord (started_at, finished_at, total, succeeded,
        failed, cancelled, model). Capped at the most recent
        MAX_HISTORY_RECORDS (50) runs. Returns ``{"runs": []}`` when
        the [history] extra is not installed or the file is missing.
        """
        try:
            from harbormaster.history import read_reembed_runs
        except ImportError:
            return {"runs": []}
        runs = read_reembed_runs()
        return {"runs": [r.model_dump(mode="json") for r in runs]}

    @app.get("/api/history/reembed/runs/diff")
    async def api_history_reembed_runs_diff(
        from_: int = Query(..., alias="from"),
        to: int = Query(...),
    ) -> dict[str, object]:
        """v13.0.0a3: parity with memory-revision diff — compare two
        completed reembed runs by index.

        Indices are zero-based offsets into the chronological list
        returned by ``/api/history/reembed/runs``. The response is a
        per-field delta dict.

        Returns 404 when either index is out of range, 503 when the
        ``[history]`` extra isn't installed.
        """
        try:
            from harbormaster.history import read_reembed_runs
        except ImportError:
            raise HTTPException(
                503,
                "[history] extra not installed; install with "
                "`pip install harbormaster-mcp[history]`",
            ) from None
        runs = read_reembed_runs()
        if from_ < 0 or from_ >= len(runs):
            raise HTTPException(404, f"from index {from_} out of range")
        if to < 0 or to >= len(runs):
            raise HTTPException(404, f"to index {to} out of range")
        a = runs[from_]
        b = runs[to]
        delta = {
            "duration_seconds": (b.finished_at - b.started_at)
            - (a.finished_at - a.started_at),
            "total": b.total - a.total,
            "succeeded": b.succeeded - a.succeeded,
            "failed": b.failed - a.failed,
            "cancelled": b.cancelled - a.cancelled,
            "model_changed": (a.model or "") != (b.model or ""),
        }
        return {
            "from_index": from_,
            "to_index": to,
            "from": a.model_dump(mode="json"),
            "to": b.model_dump(mode="json"),
            "delta": delta,
        }

    @app.get("/api/history/reembed/runs/compare")
    async def api_history_reembed_runs_compare(
        indices: str = Query(..., description="comma-separated indices, e.g. '0,2,5'"),
    ) -> dict[str, object]:
        """v15.0.0a4: N-way comparison of completed reembed runs.

        Generalises the v13.0.0a3 2-way diff to up to 4 runs (UI cap
        — beyond that the table becomes unreadable). Indices are
        zero-based offsets; duplicates are stripped but order is
        preserved.

        Returns 400 when: more than 4 indices, any non-integer, or
        empty list. Returns 404 when an index is out of range.
        """
        try:
            from harbormaster.history import read_reembed_runs
        except ImportError:
            raise HTTPException(
                503,
                "[history] extra not installed; install with "
                "`pip install harbormaster-mcp[history]`",
            ) from None

        try:
            parsed = [int(s.strip()) for s in indices.split(",") if s.strip()]
        except ValueError:
            raise HTTPException(400, f"indices must be integers: {indices!r}") from None
        if not parsed:
            raise HTTPException(400, "indices must contain at least one value")
        seen: set[int] = set()
        deduped: list[int] = []
        for idx in parsed:
            if idx not in seen:
                deduped.append(idx)
                seen.add(idx)
        if len(deduped) > 4:
            raise HTTPException(
                400,
                f"compare supports at most 4 runs; got {len(deduped)}",
            )

        runs = read_reembed_runs()
        for idx in deduped:
            if idx < 0 or idx >= len(runs):
                raise HTTPException(404, f"index {idx} out of range")
        chosen = [runs[i] for i in deduped]

        fields: list[dict[str, object]] = [
            {
                "name": "duration_seconds",
                "values": [r.finished_at - r.started_at for r in chosen],
            },
            {"name": "total", "values": [r.total for r in chosen]},
            {"name": "succeeded", "values": [r.succeeded for r in chosen]},
            {"name": "failed", "values": [r.failed for r in chosen]},
            {"name": "cancelled", "values": [r.cancelled for r in chosen]},
            {"name": "model", "values": [r.model or "" for r in chosen]},
        ]

        return {
            "indices": deduped,
            "runs": [r.model_dump(mode="json") for r in chosen],
            "fields": fields,
        }

    @app.post("/api/history/reembed/cancel")
    async def api_history_reembed_cancel() -> dict[str, object]:
        """v7.0.0a3: request cooperative cancel of a running reembed.

        Idempotent: cancelling a non-running reembed is a no-op that
        returns 200 with ``{"running": false, "cancel_requested": false}``.
        When a run IS in progress, the cancel flag is set in the state
        file; the worker observes it between hosts and exits with
        ``phase = "cancelled"``. The flag does NOT abort an in-flight
        host's reembed (a single host is the smallest atomic unit).
        """
        try:
            from harbormaster.history import request_reembed_cancel
        except ImportError:
            raise HTTPException(
                503,
                "[history] extra not installed; install with "
                "`pip install harbormaster-mcp[history]`",
            ) from None

        was_running, state = request_reembed_cancel()
        return {
            "running": was_running,
            "cancel_requested": state.cancel_requested,
            "phase": state.phase,
        }

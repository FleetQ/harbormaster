"""``await_delegated_task`` + ``await_inbox`` MCP tools (v22.1.0).

Blocking-wait surface for the async delegate flow. Instead of polling
``get_delegated_task`` or ``recall_pending_results`` in a loop, an
agent can call one of these tools and the MCP transport will hold the
request open until completion or timeout.

Semantics:

- ``await_delegated_task(job_id, timeout_seconds=900)`` — block until
  one specific job lands in a terminal state. Returns the same dict
  shape as ``get_delegated_task``; on timeout, returns the row with
  whatever ``status`` it currently has (``"queued"`` or ``"running"``).
- ``await_inbox(inbox_id, timeout_seconds=900, since=None)`` — block
  until ANY job in the inbox lands. Returns the same shape as
  ``recall_pending_results`` (no ``mark_read`` here — caller is
  expected to drain explicitly via ``recall_pending_results`` after
  reading).

Default timeout is 900 s (15 min) — matches the upper end of the
empirical max_turns guideline for non-trivial writes. Caller can pass
shorter for read-only Q&A or longer for refactor-scale tasks.
"""
from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from harbormaster.config import HarbormasterConfig


def register(mcp: FastMCP, config: HarbormasterConfig) -> None:
    @mcp.tool()
    def await_delegated_task(
        job_id: str, timeout_seconds: float = 900.0,
    ) -> dict[str, Any]:
        """Block until ``job_id`` completes or fails, or
        ``timeout_seconds`` elapses.

        Same return shape as ``get_delegated_task`` — ``status`` is
        ``"completed"``, ``"failed"``, ``"running"``, or ``"queued"``;
        the latter two indicate the wait timed out before the job
        landed. Caller can re-call with a fresh timeout to keep
        waiting.

        Returns ``{"error": "not_found", "job_id": <id>}`` if the id
        is unknown — distinguishable by the absence of ``status``.

        Prefer this over polling ``get_delegated_task`` in a loop: one
        held request is cheaper than N round-trips and the wakeup is
        immediate on completion (no poll interval).
        """
        from harbormaster.jobs import get_subsystem

        sub = get_subsystem(config)
        job = sub.store.wait_for_job(
            job_id, timeout_seconds=timeout_seconds,
        )
        if job is None:
            return {"error": "not_found", "job_id": job_id}
        return job.as_dict()

    @mcp.tool()
    def await_inbox(
        inbox_id: str = "default",
        timeout_seconds: float = 900.0,
        since: float | None = None,
    ) -> dict[str, Any]:
        """Block until at least one job in ``inbox_id`` lands in a
        terminal state, or ``timeout_seconds`` elapses.

        Returns ``{"inbox_id": "...", "results": [<job dict>, ...],
        "timed_out": <bool>}``. ``results`` is the same FIFO-on-
        completion list ``recall_pending_results`` returns; empty
        when ``timed_out`` is true.

        ``since`` (unix seconds) filters out completions the caller
        has already seen — pass the largest ``completed_at`` from the
        previous batch.

        Does NOT mark the returned jobs read. Caller should follow
        up with ``recall_pending_results(inbox_id, mark_read=True)``
        once the results have been processed, so they do not re-fire
        the next wait. Decoupled on purpose: an agent may want to
        peek-then-decide before consuming the inbox.
        """
        from harbormaster.jobs import get_subsystem

        sub = get_subsystem(config)
        jobs = sub.store.wait_for_inbox(
            inbox_id,
            timeout_seconds=timeout_seconds,
            since=since,
        )
        return {
            "inbox_id": inbox_id,
            "results": [j.as_dict() for j in jobs],
            "timed_out": len(jobs) == 0,
        }

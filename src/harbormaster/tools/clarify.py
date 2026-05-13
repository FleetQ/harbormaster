"""MCP tools for agent-to-agent clarification Q&A (v25.0.0).

Protocol:
- Subagent calls ``request_clarification(job_id, question)`` — blocks until
  the orchestrator answers or the timeout expires.
- Orchestrator calls ``await_clarification_request(job_id)`` — blocks until
  a question arrives, then answers with ``answer_clarification``.
- Orchestrator may also poll ``get_pending_clarifications`` instead of blocking.
"""
from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from harbormaster.config import HarbormasterConfig
from harbormaster.jobs.schema import STATUS_CLR_ANSWERED, STATUS_CLR_TIMED_OUT


def register(mcp: FastMCP, config: HarbormasterConfig) -> None:

    @mcp.tool()
    def request_clarification(
        job_id: str,
        question: str,
        timeout_seconds: float = 300.0,
    ) -> dict[str, Any]:
        """Ask the orchestrator a question and block until it answers.

        Called by the **subagent** during task execution when it needs more
        information.  Returns ``{"status": "answered", "answer": "<text>"}``
        on success, or ``{"status": "timed_out"}`` if no answer arrives
        within ``timeout_seconds``.

        The orchestrator learns a question is waiting via
        ``await_clarification_request(job_id)`` or by polling
        ``get_pending_clarifications(job_id)``.
        """
        from harbormaster.jobs import get_subsystem

        sub = get_subsystem(config)
        clr_id = sub.store.add_clarification(job_id, question)
        clr = sub.store.wait_for_clarification_answer(
            clr_id, timeout_seconds=timeout_seconds,
        )
        if clr is None:
            return {"error": "not_found", "clarification_id": clr_id}
        if clr.status == STATUS_CLR_ANSWERED:
            return {"status": "answered", "answer": clr.answer, "clarification_id": clr_id}
        return {"status": STATUS_CLR_TIMED_OUT, "clarification_id": clr_id}

    @mcp.tool()
    def await_clarification_request(
        job_id: str,
        timeout_seconds: float = 300.0,
    ) -> dict[str, Any]:
        """Block until the subagent asks a clarification question for ``job_id``.

        Called by the **orchestrator** to listen for questions.  Returns
        ``{"timed_out": true}`` if no question arrives within
        ``timeout_seconds``, or ``{"timed_out": false, "clarifications": [...]}``
        with one or more pending questions to answer.

        After receiving questions, call ``answer_clarification`` for each one
        so the subagent can resume.  The subagent's ``request_clarification``
        call blocks until answered or its own timeout fires.
        """
        from harbormaster.jobs import get_subsystem

        sub = get_subsystem(config)
        pending = sub.store.wait_for_clarification_request(
            job_id, timeout_seconds=timeout_seconds,
        )
        if not pending:
            return {"timed_out": True, "clarifications": []}
        return {"timed_out": False, "clarifications": [c.as_dict() for c in pending]}

    @mcp.tool()
    def answer_clarification(
        clarification_id: str,
        answer: str,
    ) -> dict[str, Any]:
        """Provide an answer to a pending clarification request.

        Called by the **orchestrator** after receiving a question via
        ``await_clarification_request`` or ``get_pending_clarifications``.
        Unblocks the subagent's ``request_clarification`` call immediately.

        Returns ``{"ok": true}`` on success, ``{"ok": false}`` if the
        clarification is not found or already answered.
        """
        from harbormaster.jobs import get_subsystem

        sub = get_subsystem(config)
        ok = sub.store.answer_clarification(clarification_id, answer)
        return {"ok": ok, "clarification_id": clarification_id}

    @mcp.tool()
    def get_pending_clarifications(
        job_id: str,
    ) -> dict[str, Any]:
        """Return all unanswered clarification questions for ``job_id``.

        Non-blocking poll alternative to ``await_clarification_request``.
        Useful when the orchestrator is already in a loop checking job status.

        Returns ``{"job_id": "...", "clarifications": [...]}``; empty list
        means no open questions.
        """
        from harbormaster.jobs import get_subsystem

        sub = get_subsystem(config)
        pending = sub.store.get_pending_clarifications(job_id)
        return {"job_id": job_id, "clarifications": [c.as_dict() for c in pending]}

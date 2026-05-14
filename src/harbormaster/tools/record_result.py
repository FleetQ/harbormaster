"""record_delegation_result MCP tool (v26.0.0).

Companion to ``delegate_task`` / ``ask_project`` / ``fan_out_ask`` in
instruction mode. The calling MCP client (the operator's interactive
``claude`` TUI) invokes this tool after executing an instruction packet
via its ``Agent`` / ``Task`` subagent. The row transitions from
``awaiting_caller`` to ``completed`` / ``failed`` and the existing
completion fan-out fires (SSE on /jobs, FleetQ Bridge publisher,
``wait_for_job`` waiters).

Contract:
  * ``status`` MUST be ``"completed"`` or ``"failed"``.
  * If ``status == "completed"`` then ``output`` MUST be provided.
  * If ``status == "failed"`` then ``error`` MUST be provided.
  * The row MUST currently be in ``awaiting_caller``; idempotent
    re-record with the same terminal status is accepted; conflicting
    terminal status is rejected.
"""
from __future__ import annotations

from typing import Literal

from mcp.server.fastmcp import FastMCP

from harbormaster.config import HarbormasterConfig


def register(mcp: FastMCP, config: HarbormasterConfig) -> None:
    @mcp.tool()
    def record_delegation_result(
        job_id: str,
        status: Literal["completed", "failed"],
        output: str | None = None,
        error: str | None = None,
        duration_ms: int = 0,
        tokens_used: int | None = None,
    ) -> str:
        """Report the outcome of an instruction-mode delegation.

        The MCP client (your interactive Claude assistant) calls this
        after running the Agent embedded in a v26 instruction packet.

        Args:
            job_id: the ``Job ID`` from the instruction packet.
            status: ``"completed"`` on success, ``"failed"`` on Agent
                failure.
            output: Agent's full return text. Required when
                ``status="completed"``.
            error: failure reason. Required when ``status="failed"``.
            duration_ms: wall-clock milliseconds the Agent took.
            tokens_used: optional cumulative token count for the
                Agent's run (used for cost attribution on /jobs).

        Returns:
            A short confirmation string, or ``"Error: ..."`` when the
            job is unknown, already in a different terminal state, or
            wasn't enqueued via instruction mode.

        Subscribers (SSE on /jobs, FleetQ Bridge completion publisher,
        ``wait_for_job`` / ``wait_for_inbox`` waiters) all fire on the
        terminal transition just like the legacy subprocess path —
        the JobStore is the single point of truth for completion fan-out.
        """
        from harbormaster.jobs import get_subsystem
        from harbormaster.jobs.schema import (
            STATUS_AWAITING_CALLER,
            STATUS_COMPLETED,
            STATUS_FAILED,
        )

        sub = get_subsystem(config)

        # Opportunistic sweep — keeps stale awaiting_caller rows from
        # accumulating between subsystem boots. The exclude_ids guard
        # ensures the row we're about to record is never collateral.
        ttl = config.delegate.awaiting_caller_timeout_seconds
        if ttl > 0:
            sub.store.sweep_stale_awaiting_caller(
                max_age_seconds=ttl, exclude_ids=frozenset({job_id}),
            )

        job = sub.store.get(job_id)
        if job is None:
            return f"Error: job {job_id!r} not found"

        # Reject record on a row that didn't originate from instruction
        # mode. Subprocess rows are JobWorker-owned; allowing external
        # writes here would let a misbehaving MCP client clobber an
        # in-flight subprocess job's status.
        if job.execution_mode != "instruction":
            return (
                f"Error: job {job_id!r} was enqueued in "
                f"{job.execution_mode!r} mode, not 'instruction'; "
                "record_delegation_result only applies to instruction-mode "
                "rows."
            )

        if job.status == status:
            # Idempotent re-record (caller might retry after a network
            # glitch). Return a status-quo message; do not re-fire
            # subscribers — they already saw the original transition.
            # First-write-wins: the original output/error/duration_ms
            # values are preserved; the second call's payload is dropped.
            return (
                f"recorded {job_id} as {status} (idempotent no-op; "
                f"first-write-wins, current output preserved)"
            )

        if job.status in (STATUS_COMPLETED, STATUS_FAILED):
            return (
                f"Error: job {job_id!r} is already in terminal state "
                f"{job.status!r}; cannot transition to {status!r}"
            )

        if job.status != STATUS_AWAITING_CALLER:
            return (
                f"Error: job {job_id!r} is in state {job.status!r}; "
                f"record_delegation_result only applies to "
                f"{STATUS_AWAITING_CALLER!r} rows."
            )

        if status == "completed":
            if output is None:
                return (
                    "Error: status='completed' requires output to be provided"
                )
            updated = sub.store.complete(
                job_id,
                output=output,
                duration_ms=duration_ms,
                tokens_used=tokens_used,
                expected_status=STATUS_AWAITING_CALLER,
            )
            if not updated:
                # Lost the CAS race — another caller (or the orphan
                # sweep) transitioned this row between our read and
                # our update. Refresh state for the caller.
                latest = sub.store.get(job_id)
                latest_status = latest.status if latest else "missing"
                return (
                    f"Error: job {job_id!r} transitioned out of "
                    f"awaiting_caller during record; latest status="
                    f"{latest_status!r} (first writer wins)"
                )
            return (
                f"recorded {job_id} as completed "
                f"(duration_ms={duration_ms}, tokens={tokens_used})"
            )

        # status == "failed"
        if error is None:
            return "Error: status='failed' requires error to be provided"
        updated = sub.store.fail(
            job_id,
            error=error,
            cid=None,
            duration_ms=duration_ms,
            tokens_used=tokens_used,
            expected_status=STATUS_AWAITING_CALLER,
        )
        if not updated:
            latest = sub.store.get(job_id)
            latest_status = latest.status if latest else "missing"
            return (
                f"Error: job {job_id!r} transitioned out of "
                f"awaiting_caller during record; latest status="
                f"{latest_status!r} (first writer wins)"
            )
        return (
            f"recorded {job_id} as failed "
            f"(duration_ms={duration_ms}, tokens={tokens_used})"
        )

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
        ``"failed"``, ``"awaiting_caller"`` (v26.0.0).
        ``output`` carries the subagent's markdown summary when
        ``status == "completed"``; ``error`` carries the
        ``"Error: ..."`` string and ``cid`` correlation id when
        ``status == "failed"``.

        v26.0.0 — when ``status == "awaiting_caller"`` and the job was
        enqueued in instruction mode, the response additionally carries
        ``instruction_packet`` (a markdown string) so a caller who lost
        track of the original ``delegate_task`` / ``ask_project``
        response can recover and re-execute it.

        Returns ``{"error": "not_found", "job_id": <id>}`` if the id
        does not match any row — distinguishable from a real backend
        failure by the absence of ``status``.
        """
        from harbormaster.jobs import get_subsystem
        from harbormaster.jobs.schema import STATUS_AWAITING_CALLER
        sub = get_subsystem(config)
        job = sub.store.get(job_id)
        if job is None:
            return {"error": "not_found", "job_id": job_id}
        payload: dict[str, Any] = dict(job.as_dict())
        if (
            job.status == STATUS_AWAITING_CALLER
            and job.execution_mode == "instruction"
        ):
            from harbormaster.instruction import (
                build_packet,
                packet_kind_for_delegate,
            )
            from harbormaster.projects import resolve_project
            try:
                cwd = resolve_project(
                    job.project, config.projects,
                    ignore_patterns=config.ignore.patterns,
                )
                cwd_str: str | None = str(cwd)
            except ValueError:
                cwd_str = None
            kind = packet_kind_for_delegate(job.allow_writes, job.auto_commit)
            # v26.0.0 — prefer the persisted rendered_prompt (full
            # grounded + suffixed text) when present. Fall back to
            # job.task for forward-compat on rows enqueued before this
            # column existed; pair with a defensive notice so a caller
            # that gets a fallback packet knows the role suffix may
            # be missing.
            recovery_prompt = job.rendered_prompt
            if recovery_prompt is None:
                recovery_prompt = (
                    f"{job.task}\n\n"
                    "WARNING: this packet was recovered without a stored "
                    "rendered prompt (pre-v26 row). The original read-only "
                    "/ writes / auto-commit role suffix is NOT present. "
                    "Honour the row's allow_writes / auto_commit flags "
                    "manually."
                )
            packet = build_packet(
                job_id=job.id,
                kind=kind,
                project=job.project,
                cwd=cwd_str,
                host=job.host,
                prompt=recovery_prompt,
                max_turns=job.max_turns,
                model_hint=job.model,
                allow_writes=job.allow_writes,
                auto_commit=job.auto_commit,
            )
            payload["instruction_packet"] = packet.to_markdown()
        return payload

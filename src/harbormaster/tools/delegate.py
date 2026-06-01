"""delegate_task MCP tool — delegates work to a project's Claude Code subagent.

The caller (agent A) authorises edits via ``allow_writes`` and chooses
between blocking (``mode="sync"``, default) and fire-and-forget
(``mode="async"``) execution. Async jobs land in a SQLite-backed
JobStore; agent A retrieves the result with ``get_delegated_task`` (or,
in v22.0.0a3+, ``recall_pending_results``).
"""
from __future__ import annotations

from typing import Literal

from mcp.server.fastmcp import FastMCP

from harbormaster.config import HarbormasterConfig
from harbormaster.instruction import execution_mode_for
from harbormaster.orchestrators import (
    detect_client_orchestrator,
    get_adapter,
    resolve_orchestrator,
)
from harbormaster.tools._grounding import build_grounded_prompt
from harbormaster.tools._helpers import run_backend_or_instruction

_READ_ONLY_SUFFIX = (
    "Read-only mode. Do NOT edit files. "
    "Report what you would do and which files you would touch. "
    "Return markdown under 500 words."
)

_WRITES_SUFFIX = (
    "You may edit files in this project. Make the change directly, "
    "then return a markdown summary under 500 words listing: "
    "(1) files changed with one-line reasons, "
    "(2) any new tests added, "
    "(3) follow-ups left for the operator. "
    "Do NOT git commit — the operator will review and commit."
)

_WRITES_AUTO_COMMIT_SUFFIX = (
    "You may edit files in this project. Make the change directly, "
    "run any relevant tests to validate, then git commit the changes "
    "with a clear conventional-commit message ('feat:', 'fix:', "
    "'refactor:' etc.). Do NOT push — the operator pushes after "
    "review. Return a markdown summary under 500 words listing: "
    "(1) files changed with one-line reasons, "
    "(2) any new tests added, "
    "(3) the commit SHA + subject, "
    "(4) follow-ups left for the operator."
)


def register(mcp: FastMCP, config: HarbormasterConfig) -> None:
    @mcp.tool()
    def delegate_task(
        name: str,
        task: str,
        deliverable: str,
        allow_writes: bool = False,
        host: str | None = None,
        model: str | None = None,
        mode: Literal["sync", "async"] = "sync",
        inbox_id: str = "default",
        max_turns: int = 10,
        auto_commit: bool = False,
        orchestrator: str | None = None,
    ) -> str:
        """Delegate a task to a project's Claude Code subagent.

        ``allow_writes`` is the caller's authorisation. ``False`` (default)
        renders a read-only prompt: the subagent is told not to edit files
        and to return a plan instead. ``True`` renders a writes-allowed
        prompt: the subagent edits files directly and returns a summary of
        what changed. The underlying ``--permission-mode bypassPermissions``
        flag is unchanged in both modes; the prompt is what gates behaviour.

        ``mode`` controls blocking vs fire-and-forget:

        - ``"sync"`` (default) blocks until the subagent finishes, then
          returns the result string — same shape as v22.0.0a1.
        - ``"async"`` enqueues the task in the JobStore, returns a
          handle string of the form ``"queued <job_id> (inbox=<id>)"``,
          and lets a background worker run it. Poll status with
          ``get_delegated_task(job_id)`` or fetch completed results
          with ``recall_pending_results(inbox_id)`` (v22.0.0a3+).

        ``inbox_id`` groups async jobs for ``recall_pending_results``;
        it has no effect when ``mode="sync"``.

        When ``[history] auto_ground = true``, the task description is
        prepended with a "Prior context" section listing the top-K past
        Q&A matches for this project.

        ``model`` is an optional alias ('haiku', 'sonnet', 'opus') or full
        model id; ``None`` = backend default. Subject to
        ``[backends.<name>] allowed_models`` whitelist when set.

        SSH/remote writes share the same gate — if ``host`` is set and
        ``allow_writes=True``, the subagent edits files on the remote host
        and the operator is responsible for pulling/diffing those changes.

        ``max_turns`` (v22.0.1) caps how many tool-use turns the
        subagent gets before ``claude -p`` exits. Default 10 matches
        the historical hardcoded value — fine for short read-only
        questions. Non-trivial writes (multi-file edits, tests,
        commit) typically need 30-80 turns; set explicitly per call
        rather than guessing. Hitting the cap surfaces as
        ``code=exit_nonzero: claude -p exit 1: (no stderr)`` because
        the subagent reaches ``max_turns_reached`` before producing
        a final result.

        ``auto_commit`` (v24.0.0a2) — only meaningful when
        ``allow_writes=True``. ``False`` (default) preserves the v22
        "subagent edits, operator commits" workflow. ``True`` swaps
        the prompt to ask the subagent to run tests + git-commit
        after edits (does NOT push — operator pushes after review).
        Set when you trust the subagent's judgement and want the
        commit step inside the delegation budget.

        ``orchestrator`` (v27.0.0) selects which calling client the
        instruction packet is rendered for ('claude', 'codex', 'gemini',
        'neutral'). None = resolve from config / MCP clientInfo,
        defaulting to 'claude'. An unknown value falls back to subprocess
        execution. No effect over SSH.
        """
        # v26.0.0 — resolve effective execution mode honouring the
        # SSH-forces-subprocess rule. Async mode crosses both paths
        # differently: subprocess-async enqueues for a JobWorker;
        # instruction-async enqueues an awaiting_caller row whose
        # packet the caller polls for via get_delegated_task.
        eff_mode = execution_mode_for(config, host)

        if mode == "async":
            # Late import to break the tools.delegate ↔ jobs.worker
            # ↔ tools._grounding circular path. The async subsystem
            # touches tool-helper modules at construction time.
            from harbormaster.jobs import get_subsystem
            from harbormaster.jobs.schema import (
                STATUS_AWAITING_CALLER,
                STATUS_QUEUED,
            )
            sub = get_subsystem(config)
            # v27.0.0 — only stay on the instruction path when the resolved
            # orchestrator has an adapter; an unknown orchestrator can't run
            # a packet, so fall through to subprocess-async (a JobWorker runs
            # it server-side).
            orch = (
                resolve_orchestrator(
                    explicit=orchestrator,
                    config=config,
                    detected=detect_client_orchestrator(),
                )
                if eff_mode == "instruction"
                else None
            )
            if eff_mode == "instruction" and get_adapter(orch or "") is not None:
                # v26.0.0 — async + instruction: enqueue as awaiting_caller,
                # return a handle. The caller polls get_delegated_task to
                # retrieve the instruction packet, then executes it.
                # Pre-render the full prompt (grounded + role suffix) so
                # the recovered packet faithfully reproduces the original.
                grounded = build_grounded_prompt(
                    question=f"{task}\n\nDeliverable: {deliverable}",
                    project=name,
                    host=host,
                    config=config,
                )
                if allow_writes:
                    suffix = (
                        _WRITES_AUTO_COMMIT_SUFFIX
                        if auto_commit else _WRITES_SUFFIX
                    )
                else:
                    suffix = _READ_ONLY_SUFFIX
                rendered = f"{grounded}\n\n{suffix}"
                job = sub.store.enqueue(
                    project=name,
                    host=host,
                    task=task,
                    deliverable=deliverable,
                    allow_writes=allow_writes,
                    model=model,
                    inbox_id=inbox_id,
                    max_turns=max_turns,
                    auto_commit=auto_commit,
                    execution_mode="instruction",
                    initial_status=STATUS_AWAITING_CALLER,
                    rendered_prompt=rendered,
                    orchestrator=orch,
                )
                return (
                    f"queued {job.id} (inbox={job.inbox_id}) in instruction "
                    f"mode. Fetch instruction packet with "
                    f"get_delegated_task({job.id!r}), execute via your "
                    f"sub-agent, and report back with record_delegation_result."
                )
            # Legacy subprocess-async path (also reached when instruction
            # mode resolved to an unknown orchestrator).
            job = sub.store.enqueue(
                project=name,
                host=host,
                task=task,
                deliverable=deliverable,
                allow_writes=allow_writes,
                model=model,
                inbox_id=inbox_id,
                max_turns=max_turns,
                auto_commit=auto_commit,
                execution_mode="subprocess",
                initial_status=STATUS_QUEUED,
            )
            return (
                f"queued {job.id} (inbox={job.inbox_id}). "
                f"Poll with get_delegated_task({job.id!r}) or fetch "
                f"completed results with recall_pending_results("
                f"inbox_id={job.inbox_id!r})."
            )

        # mode == "sync" — instruction-mode returns a packet, subprocess
        # mode preserves the v22-v25 blocking semantics.
        grounded = build_grounded_prompt(
            question=f"{task}\n\nDeliverable: {deliverable}",
            project=name,
            host=host,
            config=config,
        )
        if allow_writes:
            suffix = _WRITES_AUTO_COMMIT_SUFFIX if auto_commit else _WRITES_SUFFIX
        else:
            suffix = _READ_ONLY_SUFFIX
        full_prompt = f"{grounded}\n\n{suffix}"
        return run_backend_or_instruction(
            name=name,
            prompt=full_prompt,
            max_turns=max_turns,
            host=host,
            config=config,
            label_prefix="delegate",
            model=model,
            allow_writes=allow_writes,
            auto_commit=auto_commit,
            deliverable=deliverable,
            inbox_id=inbox_id,
            task_text=task,
            orchestrator=orchestrator,
        )

"""delegate_task MCP tool — read-only delegation, fails closed for writes in v1."""
from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from harbormaster.config import HarbormasterConfig
from harbormaster.tools._grounding import build_grounded_prompt
from harbormaster.tools._helpers import run_backend


def register(mcp: FastMCP, config: HarbormasterConfig) -> None:
    @mcp.tool()
    def delegate_task(
        name: str,
        task: str,
        deliverable: str,
        allow_writes: bool = False,
        host: str | None = None,
        model: str | None = None,
    ) -> str:
        """Delegate a task to a project's Claude Code subagent (read-only in v1).

        v1 fails closed when allow_writes=True both locally and remotely. Use
        ask_project for read-only questions, or run the task manually in the
        project's directory until v2 adds an explicit approval gate.

        When `[history] auto_ground = true`, the task description is prepended
        with a "Prior context" section listing the top-K past Q&A matches for
        this project (v1.2 phase 4).

        v21.0.0a10: ``model`` is an optional alias ('haiku', 'sonnet',
        'opus') or full model id; None = backend default. Subject to
        ``[backends.<name>] allowed_models`` whitelist when set.
        """
        if allow_writes:
            return (
                "Error: delegate_task with allow_writes=True is disabled in v1. "
                "Use ask_project for read-only questions, or run the task manually "
                "in the project's directory until v2 adds an approval gate."
            )

        # Use task + deliverable as the question for recall purposes —
        # together they describe what we're asking the subagent to do,
        # which is what matters for matching prior trajectories.
        grounded = build_grounded_prompt(
            question=f"{task}\n\nDeliverable: {deliverable}",
            project=name,
            host=host,
            config=config,
        )
        full_prompt = (
            f"{grounded}\n\n"
            "Read-only mode. Do NOT edit files. "
            "Report what you would do and which files you would touch. "
            "Return markdown under 500 words."
        )
        return run_backend(
            name=name,
            prompt=full_prompt,
            max_turns=10,
            host=host,
            config=config,
            label_prefix="delegate",
            model=model,
        )

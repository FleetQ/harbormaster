"""delegate_task MCP tool — read-only delegation, fails closed for writes in v1."""
from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from harbormaster.config import HarbormasterConfig
from harbormaster.tools._helpers import run_backend


def register(mcp: FastMCP, config: HarbormasterConfig) -> None:
    @mcp.tool()
    def delegate_task(
        name: str,
        task: str,
        deliverable: str,
        allow_writes: bool = False,
        host: str | None = None,
    ) -> str:
        """Delegate a task to a project's Claude Code subagent (read-only in v1).

        v1 fails closed when allow_writes=True both locally and remotely. Use
        ask_project for read-only questions, or run the task manually in the
        project's directory until v2 adds an explicit approval gate.
        """
        if allow_writes:
            return (
                "Error: delegate_task with allow_writes=True is disabled in v1. "
                "Use ask_project for read-only questions, or run the task manually "
                "in the project's directory until v2 adds an approval gate."
            )

        full_prompt = (
            f"Task: {task}\n\n"
            f"Deliverable: {deliverable}\n\n"
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
        )

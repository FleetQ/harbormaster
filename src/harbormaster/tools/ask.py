"""ask_project MCP tool."""
from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from harbormaster.config import HarbormasterConfig
from harbormaster.tools._grounding import build_grounded_prompt
from harbormaster.tools._helpers import run_backend


def register(mcp: FastMCP, config: HarbormasterConfig) -> None:
    @mcp.tool()
    def ask_project(
        name: str,
        question: str,
        max_turns: int = 5,
        host: str | None = None,
    ) -> str:
        """Ask a question of a project's Claude Code subagent.

        Spawns the configured backend in the project's directory; the project's
        CLAUDE.md and Serena memories auto-load. Returns ≤ 800-word markdown
        summary; full output dumped to /tmp if longer. When `host` is set
        (and != "local"), runs over SSH on that host inside the host's
        configured `remote_htdocs/<name>`.

        When `[history] auto_ground = true`, the prompt is prepended with
        a "Prior context" section listing the top-K past Q&A matches for
        this project from the per-host sqlite store (v1.2 phase 4).
        """
        grounded = build_grounded_prompt(
            question=question,
            project=name,
            host=host,
            config=config,
        )
        full_prompt = (
            f"{grounded}\n\n"
            "Return a concise markdown summary under 500 words. "
            "Focus on the answer; skip unnecessary preamble."
        )
        return run_backend(
            name=name,
            prompt=full_prompt,
            max_turns=max_turns,
            host=host,
            config=config,
            label_prefix="ask",
        )

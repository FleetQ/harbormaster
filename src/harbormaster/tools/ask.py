"""ask_project MCP tool."""
from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from harbormaster.config import HarbormasterConfig
from harbormaster.tools._grounding import build_grounded_prompt
from harbormaster.tools._helpers import run_backend_or_instruction


def register(mcp: FastMCP, config: HarbormasterConfig) -> None:
    @mcp.tool()
    def ask_project(
        name: str,
        question: str,
        max_turns: int = 5,
        host: str | None = None,
        model: str | None = None,
        orchestrator: str | None = None,
    ) -> str:
        """Ask a question of a project's Claude Code subagent.

        Behaviour depends on ``[delegate] execution_mode``:

        - ``"instruction"`` (default, v26.0.0): returns an instruction
          packet for the calling MCP client to execute via its
          ``Agent`` / ``Task`` tool. The packet carries the project's
          cwd so the agent can auto-load CLAUDE.md and Serena memories.
          The caller MUST invoke ``record_delegation_result`` to mark
          the job complete.
        - ``"subprocess"`` (legacy v22-v25): spawns the configured backend
          in the project's directory; CLAUDE.md and Serena memories
          auto-load. Returns ≤ 800-word markdown summary; full output
          dumped to /tmp if longer.

        When `host` is set (and != "local"), runs over SSH on that host
        inside the host's configured `remote_htdocs/<name>`. SSH always
        forces subprocess mode (no PTY to remote from caller's session).

        When `[history] auto_ground = true`, the prompt is prepended with
        a "Prior context" section listing the top-K past Q&A matches for
        this project from the per-host sqlite store (v1.2 phase 4).

        v21.0.0a10: ``model`` is an optional alias ('haiku', 'sonnet',
        'opus') or full model id; None = backend default. Subject to
        ``[backends.<name>] allowed_models`` whitelist when set.

        v27.0.0: ``orchestrator`` overrides which calling client the
        instruction packet is rendered for ('claude', 'codex', 'gemini',
        'neutral'). None = resolve from config / MCP clientInfo, defaulting
        to 'claude'. An unknown value falls back to subprocess execution.
        No effect in subprocess mode or over SSH.
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
        return run_backend_or_instruction(
            name=name,
            prompt=full_prompt,
            max_turns=max_turns,
            host=host,
            config=config,
            label_prefix="ask",
            model=model,
            task_text=question,
            orchestrator=orchestrator,
        )

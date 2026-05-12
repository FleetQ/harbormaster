"""delegate_task MCP tool — delegates work to a project's Claude Code subagent.

The caller (agent A) authorises edits via the ``allow_writes`` parameter.
The default stays ``False`` so existing call sites keep their read-only
semantics, but ``allow_writes=True`` now executes the task with edits
enabled instead of returning an error.
"""
from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from harbormaster.config import HarbormasterConfig
from harbormaster.tools._grounding import build_grounded_prompt
from harbormaster.tools._helpers import run_backend

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
        """Delegate a task to a project's Claude Code subagent.

        ``allow_writes`` is the caller's authorisation. ``False`` (default)
        renders a read-only prompt: the subagent is told not to edit files
        and to return a plan instead. ``True`` renders a writes-allowed
        prompt: the subagent edits files directly and returns a summary of
        what changed. The underlying ``--permission-mode bypassPermissions``
        flag is unchanged in both modes; the prompt is what gates behaviour.

        When ``[history] auto_ground = true``, the task description is
        prepended with a "Prior context" section listing the top-K past
        Q&A matches for this project.

        ``model`` is an optional alias ('haiku', 'sonnet', 'opus') or full
        model id; ``None`` = backend default. Subject to
        ``[backends.<name>] allowed_models`` whitelist when set.

        SSH/remote writes share the same gate — if ``host`` is set and
        ``allow_writes=True``, the subagent edits files on the remote host
        and the operator is responsible for pulling/diffing those changes.
        """
        # Use task + deliverable as the question for recall purposes —
        # together they describe what we're asking the subagent to do,
        # which is what matters for matching prior trajectories.
        grounded = build_grounded_prompt(
            question=f"{task}\n\nDeliverable: {deliverable}",
            project=name,
            host=host,
            config=config,
        )
        suffix = _WRITES_SUFFIX if allow_writes else _READ_ONLY_SUFFIX
        full_prompt = f"{grounded}\n\n{suffix}"
        return run_backend(
            name=name,
            prompt=full_prompt,
            max_turns=10,
            host=host,
            config=config,
            label_prefix="delegate",
            model=model,
        )

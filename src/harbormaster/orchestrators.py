"""Orchestrator adapters (v27.0.0) — provider-agnostic instruction packets.

In v26 the instruction-mode packet was hard-coupled to Claude Code: it told
the caller to use its ``Agent`` / ``Task`` tool and embedded
``subagent_type``. v27 introduces an *orchestrator adapter* layer so non-Claude
MCP clients that have their own sub-agent primitive — OpenAI Codex CLI, Gemini
CLI — receive a packet rendered in their own idiom and can auto-execute it.

Design notes (grounded in the v27 requirements / OQ validation):

- Delegation in every target CLI is **LLM-mediated** (the orchestrator model
  reads instructions and decides to spawn a sub-agent). So an adapter is mostly
  wording, not a different transport — the markdown-packet contract generalises.
- Neither Codex nor Gemini exposes a per-delegation ``cwd`` argument (unlike
  Claude's ``Agent``). Non-Claude packets therefore embed the project path **in
  the prompt body** rather than as a structured field.
- Report-back stays universal: every orchestrator calls harbormaster's own
  ``record_delegation_result`` MCP tool. The packet is explicit that this is
  NOT the orchestrator's internal job-result mechanism (e.g. Codex's
  ``report_agent_job_result``).

The ``claude`` adapter delegates to the existing
``instruction.InstructionPacket.to_markdown`` / ``instruction.build_fan_out_packet``
so the v26 output is preserved byte-for-byte (backward-compat invariant).

This module imports only ``instruction`` + ``config`` to stay cycle-free; the
tool layer (``tools/_helpers``, ``tools/fan_out``, ``tools/job_status``) calls
``resolve_orchestrator`` + ``get_adapter``.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Protocol

from harbormaster.config import HarbormasterConfig
from harbormaster.instruction import (
    INSTRUCTION_MARKER,
    InstructionPacket,
    build_fan_out_packet,
)

logger = logging.getLogger("harbormaster.orchestrators")

DEFAULT_ORCHESTRATOR = "claude"
"""Adapter used when resolution falls through to the default — preserves the
v26 packet shape for callers that don't declare an orchestrator."""


class OrchestratorAdapter(Protocol):
    """Renders instruction packets in one orchestrator's sub-agent idiom."""

    name: str

    def render_packet(self, packet: InstructionPacket) -> str: ...

    def render_fan_out(
        self,
        *,
        batch_id: str,
        targets: list[dict[str, Any]],
        synthesize: bool,
        synthesis_max_turns: int,
        model_hint: str | None,
    ) -> str: ...


# --------------------------------------------------------------------------
# Shared rendering helpers for the non-Claude adapters
# --------------------------------------------------------------------------

def _cwd_clause(cwd: str | None) -> str:
    if cwd:
        return f"the project rooted at `{cwd}`"
    return "the remote project (see the host field)"


def _writes_clause(packet: InstructionPacket) -> str:
    if not packet.allow_writes:
        return "Read-only: the sub-agent must NOT edit files."
    if packet.auto_commit:
        return (
            "Writes allowed: the sub-agent may edit files, run tests, then "
            "git-commit (do NOT push)."
        )
    return (
        "Writes allowed: the sub-agent may edit files but must NOT git-commit "
        "— the operator commits after review."
    )


def _report_back_section(job_id: str) -> str:
    return (
        "## Report the result back\n\n"
        "After the sub-agent returns, call the harbormaster MCP tool "
        "`record_delegation_result` — NOT your orchestrator's own internal "
        "job-result mechanism — with:\n\n"
        "| Argument | Value |\n"
        "|---|---|\n"
        # Plain (no repr) so an orchestrator that copies the cell verbatim
        # passes the bare id, not a quote-wrapped string that would miss
        # the row and orphan it until the timeout sweep.
        f"| `job_id` | `{job_id}` |\n"
        '| `status` | `"completed"` on success, `"failed"` on error |\n'
        "| `output` | the sub-agent's full return text (required when completed) |\n"
        "| `error` | the failure reason (required when failed) |\n"
        "| `duration_ms` | wall-clock milliseconds |\n"
        "| `tokens_used` | cumulative tokens if known, else omit |\n"
    )


def _generic_packet(
    packet: InstructionPacket,
    *,
    heading: str,
    spawn_intro: str,
    task_label: str,
    descriptor: dict[str, Any] | None = None,
) -> str:
    parts = [
        f"# {heading}\n",
        f"**Marker**: `{INSTRUCTION_MARKER}`",
        f"**Job ID**: `{packet.job_id}`",
        f"**Kind**: `{packet.kind}`",
        f"**Project**: `{packet.project}`",
        f"**Host**: `{packet.host}`" if packet.host else "**Host**: local",
        f"**Allow writes**: `{packet.allow_writes}`",
        f"**Auto commit**: `{packet.auto_commit}`",
        f"**Max turns hint**: `{packet.max_turns}`",
        "",
        "## Spawn a sub-agent\n",
        f"{spawn_intro} The sub-agent must operate on {_cwd_clause(packet.cwd)} — "
        "include that path in the task itself, since this orchestrator's "
        "sub-agents inherit the workspace rather than taking a working-directory "
        "argument.",
        "",
        _writes_clause(packet),
        "",
        f"{task_label}:",
        "",
        "```",
        packet.prompt,
        "```",
        "",
    ]
    if descriptor is not None:
        parts += [
            "Machine-readable descriptor (for programmatic clients):",
            "",
            "```json",
            json.dumps(descriptor, indent=2, ensure_ascii=False),
            "```",
            "",
        ]
    parts.append(_report_back_section(packet.job_id))
    return "\n".join(parts)


def _generic_fan_out(
    *,
    heading: str,
    spawn_line: str,
    batch_id: str,
    targets: list[dict[str, Any]],
    synthesize: bool,
    synthesis_max_turns: int,
    model_hint: str | None,
) -> str:
    targets_json = json.dumps(targets, indent=2, ensure_ascii=False)
    synth_line = (
        f"**Synthesize**: `True` — after collecting all answers, run one final "
        f"sub-agent (max_turns={synthesis_max_turns}) that summarises across "
        f"targets.\n"
        if synthesize
        else "**Synthesize**: `False`\n"
    )
    return (
        f"# {heading}\n\n"
        f"**Marker**: `{INSTRUCTION_MARKER}`\n"
        "**Kind**: `fan-out`\n"
        f"**Batch ID**: `{batch_id}`\n"
        f"**Target count**: `{len(targets)}`\n"
        f"{synth_line}"
        f"**Model hint**: `{model_hint or 'default'}`\n\n"
        "## Targets\n\n"
        f"```json\n{targets_json}\n```\n\n"
        "## Per-target execution\n\n"
        f"{spawn_line} Skip any target that carries an `error` field (or a null "
        "`job_id`) — do not spawn a sub-agent or report a result for it. For "
        "each remaining target, run the sub-agent on the project at the "
        "target's `cwd` (state the path in the task — sub-agents inherit the "
        "workspace, they take no cwd argument). After each sub-agent returns, "
        "call the harbormaster MCP tool `record_delegation_result(job_id="
        "<target.job_id>, status=..., output=..., duration_ms=...)`. Run the "
        "targets in parallel where your orchestrator supports it.\n"
    )


# --------------------------------------------------------------------------
# Concrete adapters
# --------------------------------------------------------------------------

class ClaudeAdapter:
    """v26 behaviour, preserved byte-for-byte."""

    name = "claude"

    def render_packet(self, packet: InstructionPacket) -> str:
        return packet.to_markdown()

    def render_fan_out(
        self,
        *,
        batch_id: str,
        targets: list[dict[str, Any]],
        synthesize: bool,
        synthesis_max_turns: int,
        model_hint: str | None,
    ) -> str:
        return build_fan_out_packet(
            batch_id=batch_id,
            targets=targets,
            synthesize=synthesize,
            synthesis_max_turns=synthesis_max_turns,
            model_hint=model_hint,
        )


class CodexAdapter:
    """OpenAI Codex CLI idiom — prompt-driven sub-agent delegation."""

    name = "codex"

    def render_packet(self, packet: InstructionPacket) -> str:
        return _generic_packet(
            packet,
            heading="Harbormaster instruction packet (Codex) — execute and report back",
            spawn_intro=(
                "Delegate this task to a Codex sub-agent (e.g. instruct Codex to "
                '"spawn an agent" for it).'
            ),
            task_label="Task for the sub-agent",
        )

    def render_fan_out(
        self,
        *,
        batch_id: str,
        targets: list[dict[str, Any]],
        synthesize: bool,
        synthesis_max_turns: int,
        model_hint: str | None,
    ) -> str:
        return _generic_fan_out(
            heading="Harbormaster fan-out packet (Codex) — execute N targets",
            spawn_line=(
                "Instruct Codex to spawn one sub-agent per target (\"spawn one "
                "agent per target, wait for all\")."
            ),
            batch_id=batch_id,
            targets=targets,
            synthesize=synthesize,
            synthesis_max_turns=synthesis_max_turns,
            model_hint=model_hint,
        )


class GeminiAdapter:
    """Gemini CLI (and Antigravity-family) idiom — ``@generalist`` delegation."""

    name = "gemini"

    def render_packet(self, packet: InstructionPacket) -> str:
        return _generic_packet(
            packet,
            heading="Harbormaster instruction packet (Gemini) — execute and report back",
            spawn_intro=(
                "Delegate this to the `@generalist` subagent, which runs in an "
                "isolated context with your inherited tools."
            ),
            task_label="Task for @generalist",
        )

    def render_fan_out(
        self,
        *,
        batch_id: str,
        targets: list[dict[str, Any]],
        synthesize: bool,
        synthesis_max_turns: int,
        model_hint: str | None,
    ) -> str:
        return _generic_fan_out(
            heading="Harbormaster fan-out packet (Gemini) — execute N targets",
            spawn_line=(
                "Delegate each target to the `@generalist` subagent in its own "
                "isolated context."
            ),
            batch_id=batch_id,
            targets=targets,
            synthesize=synthesize,
            synthesis_max_turns=synthesis_max_turns,
            model_hint=model_hint,
        )


class NeutralAdapter:
    """Provider-neutral packet + machine-readable JSON descriptor.

    For agentic MCP clients that have a sub-agent primitive but aren't one of
    the recognised vendors. Explicit opt-in only (never the auto fallback).
    """

    name = "neutral"

    def render_packet(self, packet: InstructionPacket) -> str:
        descriptor: dict[str, Any] = {
            "marker": INSTRUCTION_MARKER,
            "job_id": packet.job_id,
            "kind": packet.kind,
            "project": packet.project,
            "cwd": packet.cwd,
            "host": packet.host,
            "prompt": packet.prompt,
            "max_turns_hint": packet.max_turns,
            "model_hint": packet.model_hint,
            "allow_writes": packet.allow_writes,
            "auto_commit": packet.auto_commit,
            "report_back_tool": "record_delegation_result",
        }
        return _generic_packet(
            packet,
            heading="Harbormaster instruction packet — execute and report back",
            spawn_intro="Spawn a sub-agent with the task below.",
            task_label="Task",
            descriptor=descriptor,
        )

    def render_fan_out(
        self,
        *,
        batch_id: str,
        targets: list[dict[str, Any]],
        synthesize: bool,
        synthesis_max_turns: int,
        model_hint: str | None,
    ) -> str:
        return _generic_fan_out(
            heading="Harbormaster fan-out packet — execute N targets",
            spawn_line="Spawn one sub-agent per target.",
            batch_id=batch_id,
            targets=targets,
            synthesize=synthesize,
            synthesis_max_turns=synthesis_max_turns,
            model_hint=model_hint,
        )


_ORCHESTRATOR_ADAPTERS: dict[str, OrchestratorAdapter] = {
    a.name: a
    for a in (ClaudeAdapter(), CodexAdapter(), GeminiAdapter(), NeutralAdapter())
}


def register_adapter(adapter: OrchestratorAdapter) -> None:
    """Register (or override) an adapter by name.

    Seam for a future plugin registry (mirrors the backend plugin path).
    Not used by core today; present so third-party orchestrators can be
    added at runtime without refactoring call sites.
    """
    _ORCHESTRATOR_ADAPTERS[adapter.name] = adapter


def get_adapter(name: str) -> OrchestratorAdapter | None:
    """Return the adapter for ``name`` or None if unknown.

    A None return is the signal the tool layer uses to fall back to
    subprocess execution (an unrecognised orchestrator can't run a packet).
    """
    return _ORCHESTRATOR_ADAPTERS.get(name)


# --------------------------------------------------------------------------
# Resolution
# --------------------------------------------------------------------------

# clientInfo.name substrings → adapter name. Best-effort: the exact strings
# each CLI reports over MCP are not contractually fixed (OQ-6), so we match on
# a lowercased substring. 'antigravity' maps to gemini (Gemini CLI's announced
# successor).
_CLIENT_NAME_PATTERNS: tuple[tuple[str, str], ...] = (
    ("claude", "claude"),
    ("codex", "codex"),
    ("gemini", "gemini"),
    ("antigravity", "gemini"),
)


def _map_client_name(client_name: str) -> str | None:
    low = client_name.strip().lower()
    if not low:
        return None
    for pattern, adapter in _CLIENT_NAME_PATTERNS:
        if pattern in low:
            return adapter
    return None


def detect_client_orchestrator() -> str | None:
    """Best-effort: read the calling client's name from the live MCP request
    context and map it to an adapter. Returns None when unavailable.

    Reads the live ``request_ctx`` contextvar →
    ``session.client_params.clientInfo.name``. Everything is wrapped: no
    request context (e.g. unit tests, subprocess mode → ``LookupError``),
    pre-initialise sessions, or SDK shape drift all degrade to None rather
    than raising — the resolver then falls back to the default.
    """
    try:
        from mcp.server.lowlevel.server import request_ctx

        rc = request_ctx.get()
        client_params = rc.session.client_params
        if client_params is None:
            return None
        client_info = client_params.clientInfo
        if client_info is None:
            return None
        name = getattr(client_info, "name", None)
        if not isinstance(name, str):
            return None
        return _map_client_name(name)
    except Exception:
        return None


def resolve_orchestrator(
    *,
    explicit: str | None,
    config: HarbormasterConfig,
    detected: str | None,
) -> str:
    """Resolve the effective orchestrator name. Single source of truth.

    Precedence:
      1. ``explicit`` tool parameter (per-call override)
      2. ``[delegate] orchestrator`` config when != ``"auto"``
      3. ``detected`` — adapter name already mapped from the MCP clientInfo
         handshake (see :func:`detect_client_orchestrator`)
      4. :data:`DEFAULT_ORCHESTRATOR` (``"claude"`` — preserves v26 default)

    The return value may be an unknown name (when an explicit param / config
    names one); ``get_adapter`` returning None is what triggers the tool-layer
    subprocess fallback. Steps 3-4 only ever yield known adapters.
    """
    if explicit and explicit.strip():
        return explicit.strip().lower()
    cfg = config.delegate.orchestrator.strip().lower()
    if cfg and cfg != "auto":
        return cfg
    if detected:
        return detected
    return DEFAULT_ORCHESTRATOR


__all__ = [
    "DEFAULT_ORCHESTRATOR",
    "ClaudeAdapter",
    "CodexAdapter",
    "GeminiAdapter",
    "NeutralAdapter",
    "OrchestratorAdapter",
    "detect_client_orchestrator",
    "get_adapter",
    "register_adapter",
    "resolve_orchestrator",
]

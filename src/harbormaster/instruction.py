"""Instruction-mode packet builder (v26.0.0).

When ``[delegate] execution_mode = "instruction"`` the MCP tools
``delegate_task`` / ``ask_project`` / ``fan_out_ask`` do NOT spawn a
``claude -p`` subprocess. Instead they enqueue a ``delegated_jobs`` row
with status ``awaiting_caller`` and return an *instruction packet* — a
markdown-formatted string carrying the work to be executed and a
discriminator the calling MCP client recognises.

The marker ``HARBORMASTER_INSTRUCTION_V1`` is the contract. Clients that
recognise it spawn an Agent / Task subagent with the embedded prompt and
report the result via the new ``record_delegation_result`` tool. Clients
that don't recognise it see a human-readable instruction and can choose
to follow it manually; the orphan sweep
(:meth:`JobStore.sweep_stale_awaiting_caller`) cleans up unanswered rows
after the configured TTL.

This module is intentionally side-effect-free: it builds strings and
parses them. The JobStore writes happen in the tool layer
(``tools/_helpers.run_instruction``).
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Literal

from harbormaster.config import HarbormasterConfig

INSTRUCTION_MARKER = "HARBORMASTER_INSTRUCTION_V1"
"""Wire-format discriminator. Search for this substring to detect a
v26 instruction packet inside a markdown response."""

# Kind discriminator embedded in each packet so callers can pick a
# matching execution shape (read-only Q&A vs writes-allowed delegate
# vs multi-target fan-out).
PacketKind = Literal[
    "ask",
    "delegate-readonly",
    "delegate-writes",
    "delegate-writes-auto-commit",
    "fan-out",
]


@dataclass(frozen=True)
class InstructionPacket:
    """Structured view of one instruction packet — what the calling
    assistant should do, and where to report back."""

    job_id: str
    kind: PacketKind
    project: str
    cwd: str | None  # None for remote (forces subprocess upstream)
    host: str | None
    prompt: str
    max_turns: int
    model_hint: str | None
    allow_writes: bool
    auto_commit: bool

    def to_markdown(self) -> str:
        """Render this packet as markdown that any interactive Claude
        Code assistant can read and execute.

        The format is stable across patch releases: the marker, the
        ``Job ID``, ``Project``, ``Mode``, and the embedded
        ``agent-options`` JSON block are the load-bearing fields.
        """
        cwd_line = f"**Working dir**: `{self.cwd}`" if self.cwd else "**Working dir**: (remote — see host)"
        host_line = f"**Host**: `{self.host}`" if self.host else "**Host**: local"
        agent_options = {
            "description": _short_description(self.kind, self.project),
            "subagent_type": "general-purpose",
            "prompt": self.prompt,
            # Hint only — the calling assistant decides whether to honour
            # max_turns; Agent / Task tools don't have this knob directly,
            # but the prompt can include the budget as a hint.
            "max_turns_hint": self.max_turns,
            "model_hint": self.model_hint,
        }
        return (
            f"# Harbormaster instruction packet — execute and report back\n\n"
            f"**Marker**: `{INSTRUCTION_MARKER}`\n"
            f"**Job ID**: `{self.job_id}`\n"
            f"**Kind**: `{self.kind}`\n"
            f"**Project**: `{self.project}`\n"
            f"{host_line}\n"
            f"{cwd_line}\n"
            f"**Allow writes**: `{self.allow_writes}`\n"
            f"**Auto commit**: `{self.auto_commit}`\n"
            f"**Max turns hint**: `{self.max_turns}`\n\n"
            f"## Step 1 — Spawn Agent\n\n"
            f"Call your `Agent` (or `Task`) tool with the following options:\n\n"
            f"```json\n"
            f"{json.dumps(agent_options, indent=2, ensure_ascii=False)}\n"
            f"```\n\n"
            f"The agent inherits your interactive session's auth context, "
            f"so its LLM calls draw from your subscription pool — not the "
            f"Anthropic programmatic credit pool.\n\n"
            f"## Step 2 — Report result back\n\n"
            f"After the Agent returns, call `record_delegation_result` "
            f"with the arguments described below. Use the Agent's actual "
            f"return text where the description says `<Agent return text>` "
            f"— do not copy the angle-bracket placeholder verbatim.\n\n"
            f"| Argument | Type | Value |\n"
            f"|---|---|---|\n"
            f"| `job_id` | `str` | `{self.job_id!r}` |\n"
            f"| `status` | `\"completed\"` or `\"failed\"` | success path → `\"completed\"`; raised/error → `\"failed\"` |\n"
            f"| `output` | `str` (required when completed) | the Agent's full return text |\n"
            f"| `error` | `str` (required when failed) | the failure reason |\n"
            f"| `duration_ms` | `int` | wall-clock milliseconds the Agent took |\n"
            f"| `tokens_used` | `int` or `None` | cumulative tokens, if known |\n\n"
            f"Subscribers (SSE on /jobs, FleetQ Bridge completion publisher, "
            f"`wait_for_job` / `wait_for_inbox` waiters) fire identically on "
            f"both completed and failed transitions.\n"
        )


def build_packet(
    *,
    job_id: str,
    kind: PacketKind,
    project: str,
    cwd: str | None,
    host: str | None,
    prompt: str,
    max_turns: int,
    model_hint: str | None,
    allow_writes: bool,
    auto_commit: bool,
) -> InstructionPacket:
    """Factory — returns a typed packet that ``to_markdown`` renders."""
    return InstructionPacket(
        job_id=job_id,
        kind=kind,
        project=project,
        cwd=cwd,
        host=host,
        prompt=prompt,
        max_turns=max_turns,
        model_hint=model_hint,
        allow_writes=allow_writes,
        auto_commit=auto_commit,
    )


def build_fan_out_packet(
    *,
    batch_id: str,
    targets: list[dict[str, Any]],
    synthesize: bool,
    synthesis_max_turns: int,
    model_hint: str | None,
) -> str:
    """Render a fan-out instruction packet enumerating N targets.

    The fan-out shape is distinct from a single-target packet — it
    carries one envelope job id (``batch_id``) plus the list of
    per-target sub-jobs. The calling assistant spawns N parallel
    Agents (one per target), records each individually, and (if
    ``synthesize=True``) runs a final synthesis pass.
    """
    targets_json = json.dumps(targets, indent=2, ensure_ascii=False)
    synth_line = (
        f"**Synthesize**: `True` (after collecting all answers, run a "
        f"single Agent with `max_turns={synthesis_max_turns}` that "
        f"summarises across targets)\n"
    ) if synthesize else "**Synthesize**: `False`\n"
    return (
        f"# Harbormaster fan-out instruction packet — execute N targets\n\n"
        f"**Marker**: `{INSTRUCTION_MARKER}`\n"
        f"**Kind**: `fan-out`\n"
        f"**Batch ID**: `{batch_id}`\n"
        f"**Target count**: `{len(targets)}`\n"
        f"{synth_line}"
        f"**Model hint**: `{model_hint or 'default'}`\n\n"
        f"## Targets\n\n"
        f"```json\n{targets_json}\n```\n\n"
        f"## Per-target execution\n\n"
        f"For each target above, spawn an `Agent` with the target's "
        f"`prompt` and `cwd`. The agent inherits your interactive "
        f"session's auth context. After each Agent returns, call:\n\n"
        f"```\n"
        f"mcp__harbormaster__record_delegation_result(\n"
        f"    job_id=<target.job_id>,\n"
        f"    status=\"completed\" | \"failed\",\n"
        f"    output=<text>,\n"
        f"    duration_ms=<ms>,\n"
        f")\n"
        f"```\n\n"
        f"Parallel execution is encouraged — send all N Agent calls in "
        f"a single message so they run concurrently.\n"
    )


def is_instruction_packet(text: str) -> bool:
    """Return True if ``text`` is a v26 instruction packet."""
    return INSTRUCTION_MARKER in text


def extract_job_id(packet_text: str) -> str | None:
    """Pull the ``Job ID`` out of a rendered packet. Used by tests and
    callers that want to invoke ``record_delegation_result`` from a raw
    packet string without round-tripping through a structured form."""
    match = re.search(r"\*\*Job ID\*\*:\s*`([^`]+)`", packet_text)
    return match.group(1) if match else None


def _short_description(kind: PacketKind, project: str) -> str:
    label = {
        "ask": "Ask",
        "delegate-readonly": "Delegate (read-only) to",
        "delegate-writes": "Delegate (writes) to",
        "delegate-writes-auto-commit": "Delegate (writes + commit) to",
        "fan-out": "Fan-out to",
    }[kind]
    return f"{label} {project}"


def packet_kind_for_delegate(allow_writes: bool, auto_commit: bool) -> PacketKind:
    """Resolve the discriminator for a single-target delegate task
    based on the write / commit flags the caller passed."""
    if not allow_writes:
        return "delegate-readonly"
    if auto_commit:
        return "delegate-writes-auto-commit"
    return "delegate-writes"


def execution_mode_for(config: HarbormasterConfig, host: str | None) -> str:
    """Resolve effective execution mode for a (config, host) pair.

    Remote hosts always force ``"subprocess"`` regardless of config —
    the calling assistant has no PTY to the remote host.
    """
    if host is not None and host != "local":
        return "subprocess"
    return config.delegate.execution_mode


__all__ = [
    "INSTRUCTION_MARKER",
    "InstructionPacket",
    "PacketKind",
    "build_fan_out_packet",
    "build_packet",
    "execution_mode_for",
    "extract_job_id",
    "is_instruction_packet",
    "packet_kind_for_delegate",
]

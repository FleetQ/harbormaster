"""fan_out_ask MCP tool — parallel multi-project Q&A.

Asks the same question of N (host, project) targets in parallel and returns
a single markdown report concatenating per-target answers under section
headers. Concurrency capped via ThreadPoolExecutor; backend subprocess is
the bottleneck so threads work fine without asyncio.

Optional `synthesize=True` adds a second pass that asks the local backend
to produce a unified summary across all per-target answers — costs one
extra claude -p invocation, off by default.
"""
from __future__ import annotations

import secrets
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from harbormaster.backends import BackendError, get_backend
from harbormaster.config import HarbormasterConfig
from harbormaster.instruction import execution_mode_for
from harbormaster.orchestrators import (
    detect_client_orchestrator,
    get_adapter,
    resolve_orchestrator,
)
from harbormaster.projects import discover_projects, resolve_project
from harbormaster.tools._helpers import run_backend


@dataclass(frozen=True)
class _Target:
    host: str  # 'local' or alias from config.hosts / ssh_config
    project: str

    def label(self) -> str:
        return self.project if self.host == "local" else f"{self.host}/{self.project}"


def register(mcp: FastMCP, config: HarbormasterConfig) -> None:
    @mcp.tool()
    def fan_out_ask(
        question: str,
        project_filter: list[str] | None = None,
        host_filter: list[str] | None = None,
        max_concurrency: int = 5,
        max_turns: int = 3,
        synthesize: bool = False,
        synthesis_max_turns: int = 5,
        model: str | None = None,
        orchestrator: str | None = None,
    ) -> str:
        """Ask the same question of multiple projects in parallel.

        Spawns one backend subprocess per (host, project) target, capped at
        max_concurrency in flight. Returns a markdown report with one section
        per target. With synthesize=True, runs a final local backend pass
        that summarizes all per-target answers into a unified prologue.

        Args:
            question: the question to ask every target.
            project_filter: optional list of project names. None = all locally
                discovered projects (host='local' only).
            host_filter: optional list of host aliases. None = local only.
                Use e.g. ['local', 'friday'] to fan out across hosts. Remote
                hosts require an explicit project_filter.
            max_concurrency: cap parallel backend processes (default 5).
            max_turns: per-target backend max_turns (default 3).
            synthesize: if True, append a final claude -p call that produces
                a unified summary across all successful targets. Costs one
                extra subprocess + tokens.
            synthesis_max_turns: max_turns for the synthesis pass (default 5,
                higher than per-target since synthesis is more reasoning-heavy).
            model: optional alias ('haiku', 'sonnet', 'opus') or full model
                id passed to every target subprocess. None = backend default.
                Subject to ``[backends.<name>] allowed_models`` whitelist
                when set. v21.0.0a10.
            orchestrator: v27.0.0 — which calling client the fan-out
                instruction packet is rendered for ('claude', 'codex',
                'gemini', 'neutral'). None = resolve from config / MCP
                clientInfo, defaulting to 'claude'. An unknown value (or any
                remote target) falls back to the subprocess ThreadPool path.

        Returns:
            Markdown report. Per-target sections + (optionally) a synthesis
            section. Failed targets stay isolated as 'Error: ...' in their
            own section — they don't kill the whole report.
        """
        targets = _build_targets(project_filter, host_filter, config)
        if not targets:
            return (
                "Error: no targets matched the filters. "
                "Hint: for remote hosts you must pass project_filter."
            )

        full_prompt = (
            f"{question}\n\n"
            "Reply with a brief markdown answer under 150 words. "
            "Focus on the answer; skip preamble."
        )

        # v26.0.0 — when EVERY target resolves to instruction mode
        # (i.e. all targets are local AND execution_mode='instruction'),
        # return a fan-out instruction packet for the caller to execute
        # in parallel via N Agent() calls. Mixed batches keep the v25
        # subprocess-everywhere behaviour to avoid confusing hybrid
        # output shapes; operators wanting hybrid can call fan_out_ask
        # twice (one per host class). Going through execution_mode_for
        # keeps the SSH-forces-subprocess rule in a single place.
        all_instruction = all(
            execution_mode_for(
                config, None if t.host == "local" else t.host,
            ) == "instruction"
            for t in targets
        )
        # v27.0.0 — the resolved orchestrator must have an adapter to render
        # a fan-out packet; an unknown orchestrator falls through to the
        # subprocess ThreadPool path below.
        orch = resolve_orchestrator(
            explicit=orchestrator,
            config=config,
            detected=detect_client_orchestrator(),
        )
        if all_instruction and get_adapter(orch) is not None:
            return _instruction_fan_out(
                targets=targets,
                full_prompt=full_prompt,
                question=question,
                config=config,
                max_turns=max_turns,
                synthesize=synthesize,
                synthesis_max_turns=synthesis_max_turns,
                model=model,
                orchestrator=orch,
            )

        results: dict[_Target, str] = {}

        def _ask_one(target: _Target) -> tuple[_Target, str]:
            host_arg = None if target.host == "local" else target.host
            try:
                out = run_backend(
                    name=target.project,
                    prompt=full_prompt,
                    max_turns=max_turns,
                    host=host_arg,
                    config=config,
                    label_prefix="fanout",
                    model=model,
                )
            except Exception as e:  # pragma: no cover - defensive
                out = f"Error: {type(e).__name__}: {e}"
            return target, out

        with ThreadPoolExecutor(max_workers=max(1, max_concurrency)) as ex:
            futures = [ex.submit(_ask_one, t) for t in targets]
            for f in as_completed(futures):
                target, out = f.result()
                results[target] = out

        synthesis = None
        if synthesize:
            synthesis = _synthesize(
                config, question, targets, results, synthesis_max_turns,
                model=model,
            )

        return _format_report(question, targets, results, synthesis=synthesis)


def _build_targets(
    project_filter: list[str] | None,
    host_filter: list[str] | None,
    config: HarbormasterConfig,
) -> list[_Target]:
    """Resolve filter args into a concrete list of (host, project) targets."""
    targets: list[_Target] = []
    hosts = host_filter if host_filter is not None else ["local"]

    for host in hosts:
        if host == "local":
            local_names = [
                p.name for p in discover_projects(
                    config.projects, ignore_patterns=config.ignore.patterns,
                )
            ]
            for name in local_names:
                if project_filter is None or name in project_filter:
                    targets.append(_Target(host="local", project=name))
        else:
            if not project_filter:
                continue
            for name in project_filter:
                targets.append(_Target(host=host, project=name))
    return targets


def _synthesize(
    config: HarbormasterConfig,
    question: str,
    targets: list[_Target],
    results: dict[_Target, str],
    max_turns: int,
    *,
    model: str | None = None,
) -> str:
    """Spawn one local backend call that summarizes per-target answers.

    Uses Path.cwd() as the working directory — synthesis is a meta-question
    that doesn't need any project's CLAUDE.md context, just the answers
    themselves. Returns the synthesis text or a 'Synthesis skipped/failed:'
    string so the report stays self-explaining.
    """
    backend = get_backend(config)
    if backend is None:
        return "Synthesis skipped: backend 'claude' is not enabled."

    sections: list[str] = []
    for target in targets:
        out = results.get(target, "")
        if not out or out.startswith("Error:"):
            continue
        sections.append(f"### Answer from {target.label()}\n\n{out.strip()}")

    if not sections:
        return "Synthesis skipped: no successful target answers to synthesize."

    synthesis_prompt = (
        "You are synthesizing answers from multiple AI subagents to the same question. "
        "Your job is to find common themes, contradictions, and the most useful insight — "
        "not to enumerate.\n\n"
        f"## Original question\n\n{question}\n\n"
        "## Per-subagent answers\n\n"
        + "\n\n".join(sections)
        + "\n\n---\n\n"
        "Reply with a markdown summary under 300 words."
    )

    try:
        result = backend.ask_local(
            cwd=Path.cwd(),
            prompt=synthesis_prompt,
            max_turns=max_turns,
            model=model,
        )
    except BackendError as e:
        return f"Synthesis failed: {e}"
    return result.output


def _instruction_fan_out(
    *,
    targets: list[_Target],
    full_prompt: str,
    question: str,
    config: HarbormasterConfig,
    max_turns: int,
    synthesize: bool,
    synthesis_max_turns: int,
    model: str | None,
    orchestrator: str,
) -> str:
    """v26.0.0 — enqueue one ``awaiting_caller`` row per target and
    return a batch instruction packet describing all of them.

    The calling assistant spawns N parallel sub-agents, records each
    result via ``record_delegation_result``, and (if ``synthesize=True``)
    runs a single final synthesis sub-agent across the collected answers.

    v27.0.0 — ``orchestrator`` selects the adapter that renders the batch
    packet and is persisted on every row for recovery / observability.
    """
    from harbormaster.jobs import get_subsystem
    from harbormaster.jobs.schema import STATUS_AWAITING_CALLER

    sub = get_subsystem(config)
    # v26.0.1 — every row in this fan-out shares one batch_id so the
    # operator can correlate the N awaiting_caller rows back to the
    # single fan_out_ask invocation. Generated here (not inside the
    # build_fan_out_packet helper) so the same id is used on the row
    # AND in the packet envelope returned to the caller.
    batch_id = f"batch_{secrets.token_hex(6)}"
    target_packets: list[dict[str, object]] = []
    for target in targets:
        try:
            cwd = resolve_project(
                target.project, config.projects,
                ignore_patterns=config.ignore.patterns,
            )
        except ValueError:
            # Resolution failure on a target shouldn't kill the batch —
            # surface the failure inline. The caller will skip this
            # target's Agent call.
            target_packets.append({
                "job_id": None,
                "project": target.project,
                "host": "local",
                "cwd": None,
                "prompt": None,
                "error": f"project not found: {target.project}",
            })
            continue
        job = sub.store.enqueue(
            project=target.project,
            host=None,
            task=question,
            deliverable="",
            allow_writes=False,
            model=model,
            inbox_id="default",
            max_turns=max_turns,
            auto_commit=False,
            execution_mode="instruction",
            initial_status=STATUS_AWAITING_CALLER,
            rendered_prompt=full_prompt,
            batch_id=batch_id,
            orchestrator=orchestrator,
        )
        target_packets.append({
            "job_id": job.id,
            "project": target.project,
            "host": "local",
            "cwd": str(cwd),
            "prompt": full_prompt,
            "max_turns_hint": max_turns,
            "model_hint": model,
        })
    adapter = get_adapter(orchestrator)
    # Guarded upstream — the all_instruction gate only calls this when the
    # orchestrator resolves to a known adapter.
    assert adapter is not None
    return adapter.render_fan_out(
        batch_id=batch_id,
        targets=target_packets,
        synthesize=synthesize,
        synthesis_max_turns=synthesis_max_turns,
        model_hint=model,
    )


def _format_report(
    question: str,
    targets: list[_Target],
    results: dict[_Target, str],
    *,
    synthesis: str | None = None,
) -> str:
    successes = sum(1 for r in results.values() if not r.startswith("Error:"))
    lines = [
        f"# fan_out_ask: {question}",
        "",
        f"**Targets:** {len(targets)} · **Success:** {successes}/{len(targets)}",
        "",
    ]
    if synthesis is not None:
        lines.append("## Synthesis")
        lines.append("")
        lines.append(synthesis)
        lines.append("")
        lines.append("---")
        lines.append("")
    for target in targets:
        out = results.get(target, "(no result — concurrency bug?)")
        lines.append(f"## {target.label()}")
        lines.append("")
        lines.append(out)
        lines.append("")
    return "\n".join(lines)

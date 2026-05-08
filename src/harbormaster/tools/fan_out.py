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

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from harbormaster.backends import BackendError, get_backend
from harbormaster.config import HarbormasterConfig
from harbormaster.projects import discover_projects
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
                config, question, targets, results, synthesis_max_turns
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
            local_names = [p.name for p in discover_projects(config.projects)]
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
        )
    except BackendError as e:
        return f"Synthesis failed: {e}"
    return result.output


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

"""fan_out_ask MCP tool — parallel multi-project Q&A.

Asks the same question of N (host, project) targets in parallel and returns
a single markdown report concatenating per-target answers under section
headers. Concurrency capped via ThreadPoolExecutor; backend subprocess is
the bottleneck so threads work fine without asyncio.

LLM-side synthesis ("summarize all 50 answers into one") is intentionally
deferred to v1.0.0a3 — it would add another 30s+ claude -p call to every
fan-out and is better designed once we have real usage data.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass

from mcp.server.fastmcp import FastMCP

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
    ) -> str:
        """Ask the same question of multiple projects in parallel.

        Spawns one backend subprocess per (host, project) target, capped at
        max_concurrency in flight. Returns a markdown report with one section
        per target. No LLM synthesis in v1.0 — read the per-section answers
        directly.

        Args:
            question: the question to ask every target.
            project_filter: optional list of project names. None = all locally
                discovered projects (host='local' only).
            host_filter: optional list of host aliases. None = local only.
                Use e.g. ['local', 'friday'] to fan out across hosts. Remote
                hosts require an explicit project_filter (we can't enumerate
                remote projects cheaply enough to call here).
            max_concurrency: cap parallel backend processes (default 5).
            max_turns: per-target backend max_turns (default 3 — keeps fan-out
                affordable; bump for more complex questions).

        Returns:
            Markdown report. Per-target sections include either the answer or
            "Error: ..." if that target failed. Section header uses the form
            `<host>/<project>` for remote, `<project>` for local.
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

        return _format_report(question, targets, results)


def _build_targets(
    project_filter: list[str] | None,
    host_filter: list[str] | None,
    config: HarbormasterConfig,
) -> list[_Target]:
    """Resolve filter args into a concrete list of (host, project) targets.

    Local: enumerate via discover_projects, then intersect with project_filter
    if given. Remote: cannot enumerate; project_filter is required.
    """
    targets: list[_Target] = []
    hosts = host_filter if host_filter is not None else ["local"]

    for host in hosts:
        if host == "local":
            local_names = [p.name for p in discover_projects(config.projects)]
            for name in local_names:
                if project_filter is None or name in project_filter:
                    targets.append(_Target(host="local", project=name))
        else:
            # Remote: skip silently if no project_filter — caller may have
            # mixed local+remote in host_filter and only meant project_filter
            # for local. For pure-remote calls without a filter we cannot
            # produce targets, hence the explicit error in fan_out_ask.
            if not project_filter:
                continue
            for name in project_filter:
                targets.append(_Target(host=host, project=name))
    return targets


def _format_report(
    question: str,
    targets: list[_Target],
    results: dict[_Target, str],
) -> str:
    successes = sum(1 for r in results.values() if not r.startswith("Error:"))
    lines = [
        f"# fan_out_ask: {question}",
        "",
        f"**Targets:** {len(targets)} · **Success:** {successes}/{len(targets)}",
        "",
    ]
    for target in targets:
        out = results.get(target, "(no result — concurrency bug?)")
        lines.append(f"## {target.label()}")
        lines.append("")
        lines.append(out)
        lines.append("")
    return "\n".join(lines)

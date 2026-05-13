"""Budget UI surface (v14+).

Extracted from ``routes.py`` in v24.0.0a4 — the 5 budget endpoints
+ their helpers, plus a shared ``_toml_value`` helper moved to
``harbormaster.ui._toml_helpers``.

  GET /api/hosts/budget                          per-host call counts vs cap
  GET /api/tools/budget                          per-tool call counts vs cap
  GET /api/projects/budget?host=<name>           per-host-per-project triad
  GET /api/projects/{name}/budget                effective tightest-cap resolution
  PUT /api/projects/{name}/budget                write [budget] into <project>/.harbormaster.toml

The PUT writes ``[budget] daily_call_budget`` into a project-level
TOML file using a hand-written serializer (shared via
``_toml_helpers``); the GET resolves the tightest cap across the
three budget axes (per-host, per-tool, per-project).
"""
from __future__ import annotations

import time
import tomllib
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from harbormaster.config import HarbormasterConfig
from harbormaster.ui._toml_helpers import toml_value


class _ProjectBudgetPutBody(BaseModel):
    """v21.0.0a2: request body for PUT /api/projects/{name}/budget.

    Defined at module level so FastAPI's body-schema introspection
    resolves cleanly. Nesting this inside the register function
    confuses FastAPI's dependency injection (request reads end up
    interpreted as ``loc=["query", "body"]`` → 422).
    """

    model_config = ConfigDict(extra="forbid")
    daily_call_budget: int | None = Field(default=None)


def register_budget_routes(
    app: FastAPI, config: HarbormasterConfig,
) -> None:
    """Wire the budget endpoints onto ``app``. No HTML routes — no
    ``render`` arg."""

    @app.get("/api/hosts/budget")
    async def api_hosts_budget() -> dict[str, object]:
        """v14.0.0a4: per-host call counts (last 24h) vs configured
        ``daily_call_budget`` from ``[hosts.*]`` config.

        Hosts with no ``daily_call_budget`` set still appear (with
        ``budget = null``) so the operator can see all configured
        hosts in one place. Hosts NOT in config but seen as a target
        in the network_log are NOT reported — the budget is a per-
        configured-host concept.
        """
        from harbormaster.ui.network_log import network_log

        window_ms = 24 * 60 * 60 * 1000
        since_ms = int(time.time() * 1000) - window_ms
        counts = network_log.count_by_target(since_ms=since_ms)

        items: list[dict[str, object]] = []
        for host_name, host_cfg in sorted(config.hosts.items()):
            calls = counts.get(host_name, 0)
            budget = host_cfg.daily_call_budget
            usage_pct: float | None = (
                None if budget is None else round(calls / budget * 100, 1)
            )
            items.append({
                "host": host_name,
                "calls_24h": calls,
                "budget": budget,
                "usage_pct": usage_pct,
            })
        return {"window_hours": 24, "hosts": items}

    @app.get("/api/tools/budget")
    async def api_tools_budget() -> dict[str, object]:
        """v15.0.0a4: per-tool call counts (last 24h) vs configured
        ``daily_call_budget_per_tool`` from ``[budget]`` config.

        Tools with no budget set still appear (with ``budget = null``)
        when they've been called in the window — operator can see
        all activity in one place. Tools NEVER called AND with no
        budget set are NOT reported.
        """
        from harbormaster.ui.network_log import network_log

        window_ms = 24 * 60 * 60 * 1000
        since_ms = int(time.time() * 1000) - window_ms
        counts = network_log.count_by_tool(since_ms=since_ms)

        tool_budgets = config.budget.daily_call_budget_per_tool
        all_tools = sorted(set(tool_budgets.keys()) | set(counts.keys()))
        items: list[dict[str, object]] = []
        for tool_name in all_tools:
            calls = counts.get(tool_name, 0)
            budget: int | None = tool_budgets.get(tool_name)
            usage_pct: float | None = (
                None if budget is None else round(calls / budget * 100, 1)
            )
            items.append({
                "tool": tool_name,
                "calls_24h": calls,
                "budget": budget,
                "usage_pct": usage_pct,
            })
        return {"window_hours": 24, "tools": items}

    @app.get("/api/projects/budget")
    async def api_projects_budget(host: str) -> dict[str, object]:
        """v16.0.0a5: per-host-per-project call counts (last 24h) vs
        configured ``daily_call_budget`` from
        ``[hosts.<host>.projects.<project_name>]`` (carry-over #9).

        Closes the third axis of the budget triad: per-host (v14.a4)
        + per-tool (v15.a4) + per-project (this).

        ``tightest_cap`` is the minimum of the per-project budget,
        the per-host budget, and the per-tool budget for the
        applicable tools — the cap that would actually trigger first.
        ``tightest_cap_axis`` records which one won
        (``"project"`` / ``"host"`` / ``"tool"``); when no cap
        applies, it is ``null``.

        404 when ``host`` is not in ``[hosts.*]``.
        """
        host_cfg = config.hosts.get(host)
        if host_cfg is None:
            raise HTTPException(
                404,
                f"host {host!r} is not in [hosts.*] config",
            )

        from harbormaster.ui.network_log import network_log

        window_ms = 24 * 60 * 60 * 1000
        since_ms = int(time.time() * 1000) - window_ms
        project_names = sorted(host_cfg.projects.keys())
        counts = network_log.count_by_target_filtered(
            targets=project_names, since_ms=since_ms,
        )

        host_budget = host_cfg.daily_call_budget
        tool_budgets = config.budget.daily_call_budget_per_tool
        relevant_tool_caps = [
            v for k, v in tool_budgets.items()
            if k in {"ask_project", "delegate_task"} and v is not None
        ]
        per_tool_min = min(relevant_tool_caps) if relevant_tool_caps else None

        items: list[dict[str, object]] = []
        for project_name in project_names:
            proj_cfg = host_cfg.projects[project_name]
            calls = counts.get(project_name, 0)
            project_budget = proj_cfg.daily_call_budget

            cap_candidates: list[tuple[int, str]] = []
            if project_budget is not None:
                cap_candidates.append((project_budget, "project"))
            if host_budget is not None:
                cap_candidates.append((host_budget, "host"))
            if per_tool_min is not None:
                cap_candidates.append((per_tool_min, "tool"))
            if cap_candidates:
                tightest_cap, tightest_axis = min(
                    cap_candidates, key=lambda t: t[0],
                )
                tightest_cap_v: int | None = tightest_cap
                tightest_axis_v: str | None = tightest_axis
            else:
                tightest_cap_v = None
                tightest_axis_v = None

            usage_pct = (
                None
                if project_budget is None
                else round(calls / project_budget * 100, 1)
            )
            items.append({
                "project": project_name,
                "calls_24h": calls,
                "budget": project_budget,
                "usage_pct": usage_pct,
                "tightest_cap": tightest_cap_v,
                "tightest_cap_axis": tightest_axis_v,
            })
        return {
            "host": host,
            "window_hours": 24,
            "projects": items,
        }

    # v21.0.0a2: per-project budget GET + PUT.
    # ``_ProjectBudgetPutBody`` is defined at module level above so
    # FastAPI body-schema introspection resolves cleanly.

    def _read_project_budget_toml(project_path: Path) -> int | None:
        """Parse `<project>/.harbormaster.toml` and return
        `[budget] daily_call_budget` if present and > 0, else None."""
        toml_path = project_path / ".harbormaster.toml"
        if not toml_path.is_file():
            return None
        try:
            with toml_path.open("rb") as f:
                data = tomllib.load(f)
        except (OSError, tomllib.TOMLDecodeError):
            return None
        budget_section = data.get("budget")
        if not isinstance(budget_section, dict):
            return None
        v = budget_section.get("daily_call_budget")
        if isinstance(v, int) and v > 0:
            return v
        return None

    def _write_project_budget_toml(
        project_path: Path, value: int | None,
    ) -> None:
        """Atomically rewrite `<project>/.harbormaster.toml` with the
        new `[budget] daily_call_budget`. Preserves any other top-level
        keys and other tables (e.g. `[markdown]`). Removes the key
        entirely when ``value`` is None; removes the `[budget]` table
        if it becomes empty.

        Uses the shared ``toml_value`` serializer from
        ``harbormaster.ui._toml_helpers`` (extracted v24.0.0a4 so the
        accent picker can share it without circular imports).
        """
        import contextlib

        toml_path = project_path / ".harbormaster.toml"
        data: dict[str, Any] = {}
        if toml_path.is_file():
            try:
                with toml_path.open("rb") as f:
                    data = tomllib.load(f)
            except (OSError, tomllib.TOMLDecodeError):
                data = {}

        budget_section = data.get("budget")
        if not isinstance(budget_section, dict):
            budget_section = {}
        if value is None:
            budget_section.pop("daily_call_budget", None)
        else:
            budget_section["daily_call_budget"] = value
        if budget_section:
            data["budget"] = budget_section
        else:
            data.pop("budget", None)

        if not data:
            if toml_path.is_file():
                toml_path.write_text("", encoding="utf-8")
            return

        lines: list[str] = []
        scalars = {k: v for k, v in data.items() if not isinstance(v, dict)}
        tables = {k: v for k, v in data.items() if isinstance(v, dict)}
        for k, v in scalars.items():
            lines.append(f"{k} = {toml_value(v)}")
        for tname, tval in tables.items():
            if lines:
                lines.append("")
            lines.append(f"[{tname}]")
            for k, v in tval.items():
                if isinstance(v, dict):
                    continue
                lines.append(f"{k} = {toml_value(v)}")
        content = "\n".join(lines) + "\n"

        tmp = toml_path.with_suffix(toml_path.suffix + ".hm-tmp")
        try:
            tmp.write_text(content, encoding="utf-8")
            tmp.replace(toml_path)
            with contextlib.suppress(OSError):
                toml_path.chmod(0o644)
        finally:
            if tmp.exists():
                with contextlib.suppress(OSError):
                    tmp.unlink()

    def _effective_budget_for_project(name: str) -> dict[str, object]:
        """Resolve the three-axis budget for ``name`` (tightest wins).

        - per_host: minimum across hosts that list this project.
        - per_tool: tightest cap among project-targeting tools
          (ask_project / delegate_task) from ``[budget]
          .daily_call_budget_per_tool``.
        - per_project: value from ``<project>/.harbormaster.toml``
          ``[budget] daily_call_budget`` if set; otherwise from
          ``[hosts.*.projects.<name>]`` cells (tightest wins).
        """
        host_caps: list[int] = []
        for host_cfg in config.hosts.values():
            if name in host_cfg.projects and host_cfg.daily_call_budget is not None:
                host_caps.append(host_cfg.daily_call_budget)
        per_host = min(host_caps) if host_caps else None

        tool_budgets = config.budget.daily_call_budget_per_tool
        relevant = [
            v for k, v in tool_budgets.items()
            if k in {"ask_project", "delegate_task"} and v is not None
        ]
        per_tool = min(relevant) if relevant else None

        from harbormaster.projects import resolve_project as _rp

        per_project: int | None = None
        try:
            ppath = _rp(name, config.projects, ignore_patterns=config.ignore.patterns)
            per_project = _read_project_budget_toml(ppath)
        except ValueError:
            pass

        if per_project is None:
            project_cell_caps: list[int] = []
            for host_cfg in config.hosts.values():
                cell = host_cfg.projects.get(name)
                if cell is not None and cell.daily_call_budget is not None:
                    project_cell_caps.append(cell.daily_call_budget)
            if project_cell_caps:
                per_project = min(project_cell_caps)

        cap_candidates: list[tuple[int, str]] = []
        if per_host is not None:
            cap_candidates.append((per_host, "per_host"))
        if per_tool is not None:
            cap_candidates.append((per_tool, "per_tool"))
        if per_project is not None:
            cap_candidates.append((per_project, "per_project"))
        if cap_candidates:
            tightest_value, tightest_axis = min(cap_candidates, key=lambda t: t[0])
            tightest_value_v: int | None = tightest_value
            tightest_axis_v: str | None = tightest_axis
        else:
            tightest_value_v = None
            tightest_axis_v = None

        return {
            "project": name,
            "per_host": per_host,
            "per_tool": per_tool,
            "per_project": per_project,
            "tightest_cap_axis": tightest_axis_v,
            "tightest_cap_value": tightest_value_v,
        }

    @app.get("/api/projects/{name}/budget")
    async def get_project_budget(name: str) -> dict[str, object]:
        """v21.0.0a2: effective per-project budget across all three
        axes (per-host, per-tool, per-project). Tightest cap wins.
        Reads per-project override from `<project>/.harbormaster.toml`
        `[budget] daily_call_budget`.
        """
        from harbormaster.projects import (
            validate_project_name as _validate_project_name,
        )
        try:
            _validate_project_name(name)
        except ValueError as e:
            raise HTTPException(400, str(e)) from e
        return _effective_budget_for_project(name)

    @app.put("/api/projects/{name}/budget")
    async def put_project_budget(
        name: str, body: _ProjectBudgetPutBody,
    ) -> dict[str, object]:
        """v21.0.0a2: write `[budget] daily_call_budget = N` into the
        project's `.harbormaster.toml`, or remove the key when null.
        Returns the recomputed effective budget."""
        from harbormaster.projects import resolve_project as _resolve_project
        from harbormaster.projects import (
            validate_project_name as _validate_project_name,
        )

        try:
            _validate_project_name(name)
        except ValueError as e:
            raise HTTPException(400, str(e)) from e

        try:
            project_path = _resolve_project(
                name, config.projects, ignore_patterns=config.ignore.patterns,
            )
        except ValueError as e:
            raise HTTPException(404, str(e)) from e

        value = body.daily_call_budget
        if value is not None and (not isinstance(value, int) or value <= 0):
            raise HTTPException(
                400,
                "daily_call_budget must be a positive integer or null",
            )

        try:
            _write_project_budget_toml(project_path, value)
        except OSError as exc:
            raise HTTPException(500, "write failed") from exc

        return _effective_budget_for_project(name)

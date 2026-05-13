"""HTTP route handlers for the Live UI + MCP HTTP-direct endpoint.

Endpoints:
  GET  /              dashboard HTML (HTMX + Alpine + Tailwind via CDN)
  GET  /api/health    {"status":"ok", "version":"..."} — UI liveness probe
  GET  /api/projects  JSON list of discovered projects (rich ProjectInfo)
  GET  /health        FleetQ Bridge ping target (alias of /api/health)
  GET  /discover      FleetQ Bridge HTTP-tunnel-mode validation endpoint
  POST /mcp/{server}  HTTP-direct MCP routing — accepts {request_id, method,
                      params, timeout}; dispatches to the FastMCP tool registry
                      passed into create_app(config, mcp=...). 404 when mcp is
                      None or {server} is not 'harbormaster'. When the request
                      sends `Accept: text/event-stream`, the response is an
                      SSE stream of {heartbeat, result | error} events instead
                      of a single JSON document — see _stream_dispatch.

NOTE on imports: FastAPI / Jinja2 are imported eagerly at module top so
the route function annotations resolve via module globals. (PEP 563
future-annotations + lazy imports + FastAPI's get_type_hints don't mix.)
This module is only loaded when the [ui] extra is installed — pure stdio
users never hit this import path.
"""
import asyncio
import contextlib
import difflib
import json
import time
import tomllib
from collections.abc import AsyncIterator, Callable
from importlib import resources
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, ConfigDict, Field
from sse_starlette.sse import EventSourceResponse

from harbormaster import __version__
from harbormaster.backends.base import BackendError
from harbormaster.config import HarbormasterConfig
from harbormaster.graph import ManifestCache, build_graph, graph_to_mermaid
from harbormaster.projects import discover_projects

# Heartbeat cadence for SSE streams. Module-level so tests can monkeypatch
# it down to keep the suite fast. Production value is 5s — short enough to
# beat the typical 60s nginx / Cloudflare idle-read timeout, long enough
# that a fast-finishing tool sees zero heartbeat overhead.
_HEARTBEAT_INTERVAL_S: float = 5.0

# v9.0.0a1: explicit MIME-type table for the static asset route. Kept
# minimal (only the file types the UI actually serves today) so we don't
# inherit the surprises in the stdlib `mimetypes.guess_type` table on
# different OSes.
_STATIC_MEDIA_TYPES: dict[str, str] = {
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".webp": "image/webp",
    ".ico": "image/x-icon",
}


class _StreamIdSeq:
    """v9.0.0a4: per-stream monotonic SSE event id generator.

    Each ``next()`` returns a fresh string id. Used by request-scoped
    SSE generators so every emitted event carries the SSE ``id:`` line
    — which the browser's EventSource records as ``lastEventId`` and
    sends back as ``Last-Event-ID`` on reconnect. The /mcp/* dispatch
    path is request-scoped so resumption is a no-op there; the trace
    surface (``/api/dispatcher/trace``) uses span_id as its event id
    instead so cross-connection resumption works.
    """

    __slots__ = ("_n",)

    def __init__(self, start: int = 0) -> None:
        self._n = start

    def next(self) -> str:
        self._n += 1
        return str(self._n)


class McpProxyRequest(BaseModel):
    """Body schema for POST /mcp/{server} — mirrors agent-fleet's
    BridgeController::mcpCall validate() shape."""

    request_id: str | None = None
    method: str = Field(pattern="^(tools/call|tools/list)$")
    params: dict[str, Any] = Field(default_factory=dict)
    timeout: int | None = None


def _graph_to_cytoscape(graph: Any) -> dict[str, list[dict[str, dict[str, Any]]]]:
    """v21.0.0a9: shape ProjectGraph into Cytoscape elements JSON.

    Each node carries `{id, label, language}` so the dashboard can
    colour by language. Each edge carries `{id, source, target, kind}`
    where `kind` matches GraphEdge.dep_kind ("dep" / "dev_dep" /
    "transitive") so the dashboard can style edges identically to
    the Mermaid arrow style.
    """
    nodes = [
        {
            "data": {
                "id": n.name,
                "label": n.name,
                "language": n.language,
            }
        }
        for n in graph.nodes
    ]
    edges = [
        {
            "data": {
                "id": f"{e.src}->{e.dst}:{e.dep_kind}",
                "source": e.src,
                "target": e.dst,
                "kind": e.dep_kind,
            }
        }
        for e in graph.edges
    ]
    return {"nodes": nodes, "edges": edges}


def register_routes(
    app: FastAPI,
    templates: Jinja2Templates,
    config: HarbormasterConfig,
    *,
    mcp: Any | None = None,
    auth_token: str | None = None,
) -> None:
    # v3.0.0a6: auth_token is rendered into base.html as a <meta> when
    # non-empty so client-side hmFetch() can carry the bearer header
    # back to the same origin. Empty / None → meta tag is omitted and
    # plain fetch() works (loopback + no env token).
    auth_ctx: dict[str, str] = {"auth_token": auth_token} if auth_token else {}
    # v6.0.0a2: optimistic-stale threshold flows from config →
    # base.html → meta tag → JS isStale() helper. Hardcoded 5 in
    # v5.0.0a4 is now operator-configurable.
    base_ctx: dict[str, object] = {
        "optimistic_stale_seconds": config.history.optimistic_stale_seconds,
        # v21.0.0a3: surface the operator-configured accent into base.html
        # so a per-page <style> override emits when non-default.
        "ui_accent_hue": config.ui.accent_hue,
        "ui_accent_chroma": config.ui.accent_chroma,
        "ui_accent_chroma_soft": round(config.ui.accent_chroma * 0.6, 4),
    }

    def _render(
        request: Request, template: str, extra: dict[str, Any]
    ) -> HTMLResponse:
        ctx = {"version": __version__, **auth_ctx, **base_ctx, **extra}
        return templates.TemplateResponse(request, template, ctx)

    @app.get("/", response_class=HTMLResponse)
    async def dashboard(request: Request) -> HTMLResponse:
        return _render(request, "dashboard.html", {})

    @app.get("/tools/fan-out", response_class=HTMLResponse)
    async def fan_out_page(request: Request) -> HTMLResponse:
        """Multi-project fan_out_ask form (v2.1.0a5).

        Lists discovered projects with checkboxes; one question;
        configurable max_concurrency. Submits to the existing
        `POST /mcp/harbormaster fan_out_ask` and renders the
        aggregated result.
        """
        project_names = sorted(p.name for p in discover_projects(config.projects, ignore_patterns=config.ignore.patterns))
        host_labels = ["local", *sorted(config.hosts.keys())]
        return _render(
            request,
            "fan_out.html",
            {
                "project_names": project_names,
                "host_labels": host_labels,
            },
        )

    # v23.0.0a3: Network UI surface (HTML + 5 endpoints) extracted to
    # ``harbormaster.ui.routes_network``. All 6 endpoints register
    # here in one place instead of being split around /api/hosts/budget.
    from harbormaster.ui.routes_network import register_network_routes
    register_network_routes(app, config, _render)

    @app.get("/api/hosts/budget")
    async def api_hosts_budget() -> dict[str, object]:
        """v14.0.0a4: per-host call counts (last 24h) vs configured
        ``daily_call_budget`` from ``[hosts.*]`` config.

        Response shape::

            {
                "window_hours": 24,
                "hosts": [
                    {"host": "alpha", "calls_24h": 12, "budget": 100,
                     "usage_pct": 12.0},
                    {"host": "beta",  "calls_24h": 0,  "budget": null,
                     "usage_pct": null}
                ]
            }

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

        Response shape mirrors ``/api/hosts/budget``::

            {
                "window_hours": 24,
                "tools": [
                    {"tool": "ask_project", "calls_24h": 12,
                     "budget": 1000, "usage_pct": 1.2},
                    {"tool": "fan_out_ask", "calls_24h": 0,
                     "budget": 100, "usage_pct": 0.0},
                    {"tool": "list_projects", "calls_24h": 5,
                     "budget": null, "usage_pct": null}
                ]
            }

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
        # Union: every tool in budget config + every tool seen in
        # the window (so we report both "configured but never called"
        # and "called but unbudgeted").
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

        Response shape mirrors ``/api/tools/budget``::

            {
                "host": "<name>",
                "window_hours": 24,
                "projects": [
                    {"project": "frontend", "calls_24h": 12,
                     "budget": 50, "usage_pct": 24.0,
                     "tightest_cap": 50,
                     "tightest_cap_axis": "project"},
                    ...
                ]
            }

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

        # The per-host budget applies to every project on this host.
        host_budget = host_cfg.daily_call_budget
        # Per-tool budget — tightest across "ask_project" and
        # "delegate_task" since those are the project-targeting tools.
        # The dict may have other tools (fan_out_ask etc.); we only
        # care about the project-budget intersection.
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

            # tightest cap across the three axes; record which one won.
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

    # v21.0.0a2: per-project budget GET + PUT. The PUT writes
    # `[budget] daily_call_budget = N` to `<project>/.harbormaster.toml`
    # (or removes the key when null). GET returns the *effective* cap
    # across the per-host / per-tool / per-project axes — tightest wins,
    # matching the dispatcher's actual budget enforcement.
    class _ProjectBudgetPutBody(BaseModel):
        model_config = ConfigDict(extra="forbid")
        daily_call_budget: int | None = Field(default=None)

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

        Hand-written serializer — there's no stdlib TOML writer and
        adding tomli-w for a single 2-line table is over-spec.
        """
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

        # If the file becomes empty AND it was originally absent, leave
        # it absent. If it originally existed, write an empty file
        # rather than deleting (operator may have meant to keep it).
        if not data:
            if toml_path.is_file():
                toml_path.write_text("", encoding="utf-8")
            return

        lines: list[str] = []
        # Top-level scalars first, then tables.
        scalars = {k: v for k, v in data.items() if not isinstance(v, dict)}
        tables = {k: v for k, v in data.items() if isinstance(v, dict)}
        for k, v in scalars.items():
            lines.append(f"{k} = {_toml_value(v)}")
        for tname, tval in tables.items():
            if lines:
                lines.append("")
            lines.append(f"[{tname}]")
            for k, v in tval.items():
                if isinstance(v, dict):
                    # Skip nested tables — schema-policed elsewhere.
                    continue
                lines.append(f"{k} = {_toml_value(v)}")
        content = "\n".join(lines) + "\n"

        tmp = toml_path.with_suffix(toml_path.suffix + ".hm-tmp")
        try:
            tmp.write_text(content, encoding="utf-8")
            tmp.replace(toml_path)
            import contextlib
            with contextlib.suppress(OSError):
                toml_path.chmod(0o644)
        finally:
            if tmp.exists():
                import contextlib
                with contextlib.suppress(OSError):
                    tmp.unlink()

    def _toml_value(v: object) -> str:
        if isinstance(v, bool):
            return "true" if v else "false"
        if isinstance(v, int):
            return str(v)
        if isinstance(v, float):
            return repr(v)
        if isinstance(v, str):
            # Basic-string with escaping for the cases we expect.
            escaped = v.replace("\\", "\\\\").replace('"', '\\"')
            return f'"{escaped}"'
        if isinstance(v, list):
            return "[" + ", ".join(_toml_value(x) for x in v) + "]"
        return f'"{v!s}"'

    def _effective_budget_for_project(name: str) -> dict[str, object]:
        """Resolve the three-axis budget for `name` (tightest wins).

        - per_host: minimum across hosts that list this project.
        - per_tool: tightest cap among project-targeting tools
          (ask_project / delegate_task) from `[budget]
          .daily_call_budget_per_tool`.
        - per_project: value from `<project>/.harbormaster.toml`
          `[budget] daily_call_budget` if set; otherwise None.
        """
        # per_host
        host_caps: list[int] = []
        for host_cfg in config.hosts.values():
            if name in host_cfg.projects and host_cfg.daily_call_budget is not None:
                host_caps.append(host_cfg.daily_call_budget)
            elif name in host_cfg.projects:
                # host with project entry but no daily_call_budget; skip
                pass
        per_host = min(host_caps) if host_caps else None

        # per_tool
        tool_budgets = config.budget.daily_call_budget_per_tool
        relevant = [
            v for k, v in tool_budgets.items()
            if k in {"ask_project", "delegate_task"} and v is not None
        ]
        per_tool = min(relevant) if relevant else None

        # per_project — from .harbormaster.toml; if no override, fall
        # back to the [hosts.*.projects.<name>] cells (tightest wins).
        from harbormaster.projects import resolve_project as _rp

        per_project: int | None = None
        try:
            ppath = _rp(name, config.projects, ignore_patterns=config.ignore.patterns)
            per_project = _read_project_budget_toml(ppath)
        except ValueError:
            ppath = None

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
        else:
            tightest_value = None
            tightest_axis = None

        return {
            "project": name,
            "per_host": per_host,
            "per_tool": per_tool,
            "per_project": per_project,
            "tightest_cap_axis": tightest_axis,
            "tightest_cap_value": tightest_value,
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

    def _user_config_toml_path() -> Path:
        """v21.0.0a3: resolve the operator's user-level config.toml.

        Uses the same XDG search as `_config_search_paths` but always
        targets the user-scope file (never `.harbormaster.toml` in the
        CWD) so the accent picker rewrites a single canonical file.
        """
        import os as _os

        xdg = _os.environ.get("XDG_CONFIG_HOME") or "~/.config"
        return Path(_os.path.expandvars(xdg)).expanduser() / "harbormaster" / "config.toml"

    def _write_accent_toml(hue: float, chroma: float) -> None:
        """v21.0.0a3: atomically write `[ui] accent_hue/accent_chroma`
        into the user config.toml. Preserves existing top-level scalars
        and tables; only the two `[ui]` keys are mutated.

        Hand-written serializer — same pattern as `_write_project_budget_toml`.
        """
        toml_path = _user_config_toml_path()
        toml_path.parent.mkdir(parents=True, exist_ok=True)

        data: dict[str, Any] = {}
        if toml_path.is_file():
            try:
                with toml_path.open("rb") as f:
                    data = tomllib.load(f)
            except (OSError, tomllib.TOMLDecodeError):
                data = {}

        ui_section = data.get("ui")
        if not isinstance(ui_section, dict):
            ui_section = {}
        ui_section["accent_hue"] = float(hue)
        ui_section["accent_chroma"] = float(chroma)
        data["ui"] = ui_section

        lines: list[str] = []
        scalars = {k: v for k, v in data.items() if not isinstance(v, dict)}
        tables = {k: v for k, v in data.items() if isinstance(v, dict)}
        for k, v in scalars.items():
            lines.append(f"{k} = {_toml_value(v)}")
        for tname, tval in tables.items():
            if lines:
                lines.append("")
            lines.append(f"[{tname}]")
            for k, v in tval.items():
                if isinstance(v, dict):
                    continue
                lines.append(f"{k} = {_toml_value(v)}")
        content = "\n".join(lines) + "\n"

        tmp = toml_path.with_suffix(toml_path.suffix + ".hm-tmp")
        try:
            tmp.write_text(content, encoding="utf-8")
            tmp.replace(toml_path)
            import contextlib
            with contextlib.suppress(OSError):
                toml_path.chmod(0o644)
        finally:
            if tmp.exists():
                import contextlib
                with contextlib.suppress(OSError):
                    tmp.unlink()

    @app.get("/api/settings/accent")
    async def get_accent() -> dict[str, float]:
        """v21.0.0a3: current operator-configured accent (OKLCH hue/chroma).

        Returns the values from the loaded `[ui]` section — defaults
        (290.0 / 0.22) when no operator override is present.
        """
        return {
            "hue": float(config.ui.accent_hue),
            "chroma": float(config.ui.accent_chroma),
        }

    @app.put("/api/settings/accent")
    async def put_accent(body: dict[str, float]) -> JSONResponse:
        """v21.0.0a3: persist accent to `~/.config/harbormaster/config.toml`.

        Validates 0 <= hue <= 360 and 0 <= chroma <= 0.30. Atomic
        tmpfile+rename. Mutates the in-process `config.ui` so SSR-side
        emission of the override `<style>` reflects the new value on
        the next page load without a restart.
        """
        try:
            hue = float(body.get("hue", 290.0))
            chroma = float(body.get("chroma", 0.22))
        except (TypeError, ValueError):
            return JSONResponse({"error": "invalid payload"}, status_code=400)
        if not (0.0 <= hue <= 360.0):
            return JSONResponse({"error": "hue out of range"}, status_code=400)
        if not (0.0 <= chroma <= 0.30):
            return JSONResponse({"error": "chroma out of range"}, status_code=400)

        try:
            _write_accent_toml(hue, chroma)
        except OSError as exc:
            raise HTTPException(500, "write failed") from exc

        # Live update — next render of base.html emits the new override.
        config.ui.accent_hue = hue
        config.ui.accent_chroma = chroma
        return JSONResponse({"hue": hue, "chroma": chroma, "ok": True})

    # v23.0.0a1: Delegated Jobs UI surface extracted to
    # ``harbormaster.ui.routes_jobs`` — 5 endpoints, same registration
    # order as the pre-v23.0.0a1 inline block. See module docstring
    # there for the full rationale.
    from harbormaster.ui.routes_jobs import register_jobs_routes
    register_jobs_routes(app, config, _render)

    @app.get("/projects/{name}", response_class=HTMLResponse)
    async def project_detail(
        name: str, request: Request, host: str | None = None,
    ) -> HTMLResponse:
        """Per-project detail page (v2.1.0a2).

        Renders git log + Serena memories + path for the named project.
        Local-only when `host` is None; pass `?host=<label>` for remote.
        404s when the project isn't discoverable in the configured glob
        (local) or absent on the remote host.
        """
        from harbormaster.projects import validate_project_name
        from harbormaster.tools.projects import _local_status, _remote_status

        try:
            validate_project_name(name)
        except ValueError as e:
            raise HTTPException(400, f"invalid project name: {e}") from e

        if host is not None and host != "local":
            md = _remote_status(host, name, config)
            project_dict: dict[str, object] | None = None
        else:
            # Find the project metadata for the header card.
            project_dict = next(
                (p.as_dict() for p in discover_projects(config.projects, ignore_patterns=config.ignore.patterns)
                 if p.name == name),
                None,
            )
            if project_dict is None:
                raise HTTPException(
                    404,
                    f"project {name!r} not found in configured globs. "
                    f"Check [projects].glob in your config.",
                )
            md = _local_status(name, config)

        # _local_status / _remote_status start their error responses with
        # "Error:" — surface those as 404 / 500 rather than a confusing
        # success page that just shows the error string.
        if isinstance(md, str) and md.startswith("Error:"):
            raise HTTPException(404, md)

        return _render(
            request,
            "project_detail.html",
            {
                "project_name": name,
                "host": host or "local",
                "project": project_dict,
                "status_markdown": md,
            },
        )

    @app.get("/static/{path:path}")
    async def static_asset(path: str) -> Response:
        """Serve a packaged static asset from harbormaster/ui/static/.

        v9.0.0a1: ships the vendored Tailwind v4 stylesheet
        (`tailwind.css`) so the dashboard no longer relies on the
        Tailwind v3 CDN script. Resolves the file via
        ``importlib.resources`` so it works inside zipped wheels.

        Path traversal is blocked: any '..' or absolute path 404s
        before resolution. Symlinks pointing outside the static dir
        also 404 (resolved-path containment check).
        """
        if ".." in path.split("/") or path.startswith("/"):
            raise HTTPException(status_code=404)
        try:
            base = resources.files("harbormaster.ui").joinpath("static")
            target = base.joinpath(path)
        except (ModuleNotFoundError, FileNotFoundError) as exc:
            raise HTTPException(status_code=404) from exc
        # `MultiplexedPath` (namespace pkgs) and zip-importer Traversables
        # both expose `.is_file()`; use it as the existence/type probe.
        if not target.is_file():
            raise HTTPException(status_code=404)
        # Containment check via the filesystem `Path` form when available
        # (regular installs). For zipped wheels the resource API enforces
        # its own boundary; the early '..' guard above already rejects
        # the only client-controlled escape vector.
        try:
            base_resolved = Path(str(base)).resolve()
            target_resolved = Path(str(target)).resolve()
            if not str(target_resolved).startswith(str(base_resolved) + "/"):
                raise HTTPException(status_code=404)
        except OSError as exc:
            raise HTTPException(status_code=404) from exc
        media_type = _STATIC_MEDIA_TYPES.get(
            Path(path).suffix.lower(), "application/octet-stream"
        )
        return Response(
            content=target.read_bytes(),
            media_type=media_type,
            headers={"cache-control": "public, max-age=300"},
        )

    @app.get("/api/health")
    async def api_health() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    @app.post("/api/auth/cookie")
    async def set_auth_cookie(request: Request) -> Response:
        """v12.0.0a6: bridge bearer-header auth to a cookie that
        browser EventSource can carry.

        Browsers can't set custom headers on EventSource connections,
        so SSE streams previously needed a query-param token (less
        secure — the token sat in URLs and access logs). This endpoint
        is itself bearer-protected by the global middleware: hitting
        it with a valid `Authorization: Bearer ...` header sets the
        `hm-auth` cookie carrying the same value, so all subsequent
        SSE / fetch calls authenticate via the cookie WITHOUT needing
        to be in the URL.

        Cookie attributes:
          - HttpOnly:  not readable by JS (defence against XSS).
          - SameSite=Strict: never sent cross-origin.
          - Secure:    set when the request scheme is https.
          - Max-Age:   12 hours (operator session lifetime).
          - Path=/:    valid for every endpoint under the UI.

        Auth shape: the middleware accepts EITHER the Bearer header
        OR the `hm-auth` cookie, so this endpoint can be called the
        first time with a header, then ignored thereafter.
        """
        from harbormaster.transport import HM_AUTH_COOKIE_NAME

        # Extract the token the middleware just validated. The header
        # is "Bearer <token>"; we strip the prefix to get the raw
        # value for the cookie. A request reaching this handler
        # already passed middleware so we know one of {header, cookie}
        # is present and valid.
        authz = request.headers.get("Authorization", "")
        if authz.startswith("Bearer "):
            token = authz[len("Bearer "):]
        else:
            # Already authenticated via cookie — re-set it to refresh
            # the Max-Age window. (Idempotent: same value, same path.)
            token = request.cookies.get(HM_AUTH_COOKIE_NAME, "")
        if not token:
            raise HTTPException(401, "no token to bind to cookie")
        is_https = request.url.scheme == "https"
        resp = Response(
            content='{"ok": true}',
            media_type="application/json",
            status_code=200,
        )
        resp.set_cookie(
            key=HM_AUTH_COOKIE_NAME,
            value=token,
            max_age=12 * 60 * 60,  # 12h
            httponly=True,
            samesite="strict",
            secure=is_https,
            path="/",
        )
        return resp

    # v23.0.0a4: Dispatcher UI surface extracted to
    # ``harbormaster.ui.routes_dispatcher``.
    from harbormaster.ui.routes_dispatcher import register_dispatcher_routes
    register_dispatcher_routes(app, config, _render)

    @app.get("/api/bridge/status")
    async def api_bridge_status() -> dict[str, object]:
        """FleetQ bridge status — config + live runtime (v3.0.0a2).

        Returns both the *configured* state (was bridge wiring set up?)
        and the *runtime* state (is it actually connected right now?).
        Runtime state is read from the cross-process state file the
        harbormaster-mcp writer maintains; staleness is computed against
        a 30s freshness window so a dead writer flips the badge to
        ``stale`` instead of incorrectly showing ``connected``.
        """
        import os as _os

        api_token_present = bool(
            _os.environ.get(config.fleetq.api_token_env, "").strip()
        )

        runtime: dict[str, object] = {"available": False}
        try:
            from harbormaster.fleetq.state import read_bridge_state

            view = read_bridge_state()
            runtime = {
                "available": True,
                "state_file_present": view.state_file_present,
                "stale": view.stale,
                "age_seconds": view.age_seconds,
                "connected": view.state.connected,
                "subscribed": view.state.subscribed,
                "team_id": view.state.team_id,
                "session_id": view.state.session_id,
                "last_heartbeat": view.state.last_heartbeat,
                "last_error": view.state.last_error,
                "writer_pid": view.state.writer_pid,
            }
        except ImportError:
            # [fleetq] extra not installed — the runtime block is opt-in.
            pass

        return {
            "fleetq_enabled": config.fleetq.enabled,
            "register_as_bridge": config.fleetq.register_as_bridge,
            "base_url": config.fleetq.base_url,
            "api_token_env": config.fleetq.api_token_env,
            "api_token_present": api_token_present,
            "write_trajectories": config.fleetq.write_trajectories,
            "write_kg": config.fleetq.write_kg,
            "kg_extractor": config.fleetq.kg_extractor,
            "heartbeat_interval": config.fleetq.heartbeat_interval,
            "runtime": runtime,
        }

    # v23.0.0a5: History admin UI surface extracted to
    # ``harbormaster.ui.routes_history``. 6 endpoints (POST reembed,
    # POST reembed/cancel, GET state, GET runs, GET runs/diff,
    # GET runs/compare). Final routes-split alpha before v23.0.0 GA.
    from harbormaster.ui.routes_history import register_history_routes
    register_history_routes(app, config)

    @app.get("/api/recall")
    async def api_recall(
        question: str,
        project: str | None = None,
        top_k: int | None = None,
        min_similarity: float | None = None,
        host: str | None = None,
    ) -> dict[str, object]:
        """Browser-friendly wrapper around the `recall_qa` MCP tool
        (v2.1.0a3). Equivalent to POST /mcp/harbormaster with
        method='tools/call' name='recall_qa' but returns the raw
        result dict so the dashboard can `await fetch().json()` and
        skip the MCP content-envelope unwrap dance.
        """
        if not question.strip():
            return {
                "enabled": False,
                "matches": [],
                "host": host or "local",
                "message": "question required",
            }
        if not config.history.enabled:
            return {
                "enabled": False,
                "matches": [],
                "host": host or "local",
                "message": "[history] is disabled in config",
            }
        try:
            from harbormaster.history import get_embedding_backend
        except ImportError:
            return {
                "enabled": False,
                "matches": [],
                "host": host or "local",
                "message": "the [history] extra is not installed",
            }
        from harbormaster.tools.recall import _recall_one_host

        backend = get_embedding_backend(config)
        effective_top_k = top_k if top_k is not None else config.history.default_top_k
        effective_min_sim = (
            min_similarity
            if min_similarity is not None
            else config.history.default_min_similarity
        )
        if host == "all":
            targets: list[str | None] = [None, *sorted(config.hosts.keys())]
            all_matches: list[Any] = []
            errors: dict[str, str] = {}
            for target in targets:
                matches, err = _recall_one_host(
                    config=config,
                    host=target,
                    question=question,
                    top_k=effective_top_k,
                    project=project,
                    min_similarity=effective_min_sim,
                    backend=backend,
                )
                if err is not None:
                    errors[target if target is not None else "local"] = err
                    continue
                all_matches.extend(matches)
            all_matches.sort(key=lambda m: m.score, reverse=True)
            merged = all_matches[:effective_top_k]
            result: dict[str, object] = {
                "enabled": True,
                "backend": backend.name,
                "host": "all",
                "hosts_searched": [t if t is not None else "local" for t in targets],
                "matches": [m.to_dict() for m in merged],
            }
            if errors:
                result["errors"] = errors
            return result

        matches, err = _recall_one_host(
            config=config,
            host=host,
            question=question,
            top_k=effective_top_k,
            project=project,
            min_similarity=effective_min_sim,
            backend=backend,
        )
        if err is not None:
            return {
                "enabled": True,
                "backend": backend.name,
                "host": host or "local",
                "matches": [],
                "message": err,
            }
        return {
            "enabled": True,
            "backend": backend.name,
            "host": host or "local",
            "matches": [m.to_dict() for m in matches],
        }

    @app.get("/api/trajectories")
    async def api_trajectories(
        project: str | None = None,
        host: str | None = None,
        limit: int = 20,
    ) -> dict[str, object]:
        """Recent Q&A trajectories from the per-host store (v2.1.0a6).

        Powers the project-detail "Recent Q&A" section. Returns rows
        ordered by `created_at` desc, optionally filtered by project.
        Soft-fails to `{enabled: false, ...}` when [history] is off
        or the [history] extra isn't installed — same shape as
        /api/recall.
        """
        if limit <= 0 or limit > 200:
            limit = 20
        if not config.history.enabled:
            return {
                "enabled": False,
                "trajectories": [],
                "host": host or "local",
                "message": "[history] is disabled in config",
            }
        try:
            from harbormaster.history import (
                QAStore,
                get_embedding_backend,
            )
        except ImportError:
            return {
                "enabled": False,
                "trajectories": [],
                "host": host or "local",
                "message": "the [history] extra is not installed",
            }
        backend = get_embedding_backend(config)
        try:
            store = QAStore.open(
                db_dir=config.history.db_dir,
                host=host,
                embedding_backend=backend,
                embedding_dim=config.history.embedding_dim,
            )
        except Exception as e:  # noqa: BLE001 - surface store errors to UI
            return {
                "enabled": True,
                "trajectories": [],
                "host": host or "local",
                "message": f"history store unavailable: {e}",
            }
        try:
            rows = store.list_recent(project=project, limit=limit)
        finally:
            store.close()
        return {
            "enabled": True,
            "host": host or "local",
            "trajectories": [m.to_dict() for m in rows],
        }

    @app.get("/api/plugins")
    async def api_plugins(host: str | None = None) -> dict[str, object]:
        """Plugin discovery + status (v2.1.0a1).

        Mirrors `harbormaster-mcp plugins list` for browser consumption.
        Each entry point is categorized:

          - "loaded"          : enabled + dist in allowlist + ep discovered
          - "not-allowlisted" : enabled + ep discovered but dist not in allowlist
          - "disabled"        : ep discovered but [plugins].enabled = false
          - "no-dist-name"    : ep present but legacy metadata
          - "missing"         : dist in allowlist but NO ep discovered

        v14.0.0a6: optional ``?host=<name>`` SSHs to that host (must be
        in ``[hosts.*]``) and returns its discovery result. The remote
        host runs ``harbormaster-mcp plugins list --json`` over SSH;
        any SSH/parse failure is returned as ``{..., "error": "<msg>"}``
        with empty plugins. ``host=local`` and missing host both keep
        the existing local-discovery behavior.

        v15.0.0a2: ``?host=all`` queries every configured host
        concurrently via ``asyncio.gather`` and returns a merged
        envelope::

            {"hosts": {"<name>": <per-host-payload>, ...}}

        Each per-host payload is the same shape as the single-host
        response (with optional ``error`` key on degraded paths).
        ``"local"`` is included as a key with the local discovery
        result. Errors NEVER raise — degraded hosts just carry the
        ``error`` field.
        """
        # v15.0.0a2: ?host=all — concurrent fan-out across all hosts.
        if host == "all":
            from harbormaster.plugins import query_remote_plugins

            local_payload = await api_plugins(host=None)
            host_names = sorted(config.hosts.keys())

            async def _one(name: str) -> tuple[str, dict[str, object]]:
                cfg_h = config.hosts[name]
                # query_remote_plugins is sync (subprocess.run); offload
                # to a thread so concurrent SSHs actually overlap rather
                # than serialise on the event loop.
                payload = await asyncio.to_thread(
                    query_remote_plugins, cfg_h
                )
                return name, payload

            if host_names:
                pairs = await asyncio.gather(*(_one(n) for n in host_names))
            else:
                pairs = []
            merged: dict[str, dict[str, object]] = {"local": local_payload}
            for name, payload in pairs:
                merged[name] = payload
            return {"hosts": merged}

        # v14.0.0a6: cross-host shortcut. Local fallback when host is
        # unset / "local" — preserves the v2.1.0a1 behavior byte-for-byte.
        if host is not None and host != "local":
            host_cfg = config.hosts.get(host)
            if host_cfg is None:
                raise HTTPException(
                    404,
                    f"host {host!r} is not in [hosts.*] config",
                )
            from harbormaster.plugins import query_remote_plugins
            return query_remote_plugins(host_cfg)

        from harbormaster.plugins import (
            _entry_point_distribution_name,
            discover_entry_points,
        )

        enabled = config.plugins.enabled
        allowlist = set(config.plugins.allow)
        eps = discover_entry_points()

        rows: list[dict[str, object]] = []
        seen: set[str] = set()
        for ep in eps:
            dist = _entry_point_distribution_name(ep)
            if dist is not None:
                seen.add(dist)
            if dist is None:
                status = "no-dist-name"
            elif not enabled:
                status = "disabled"
            elif dist in allowlist:
                status = "loaded"
            else:
                status = "not-allowlisted"
            rows.append(
                {"status": status, "dist_name": dist, "entry_point": ep.name}
            )

        for dist in sorted(allowlist - seen):
            rows.append(
                {"status": "missing", "dist_name": dist, "entry_point": None}
            )

        return {
            "enabled": enabled,
            "allow": sorted(allowlist),
            "discovered_count": len(eps),
            "plugins": rows,
        }


    @app.get("/api/config/diff")
    async def api_config_diff(
        host: str,
        format: str = "json",
    ) -> Response:
        """v15.0.0a2: unified diff between local + remote config text.

        Reads the local ``harbormaster.toml`` from the same search paths
        as ``load_config`` and SSHs to the remote host for ``cat
        ~/.config/harbormaster.toml`` via :func:`query_remote_config`.

        v16.0.0a4: ``?format=html`` returns a side-by-side HTML diff
        rendered via ``difflib.HtmlDiff`` (mirrors the v13.a3 memory-
        revisions side-by-side toggle pattern). The default
        ``?format=json`` shape is unchanged.

        JSON response shape::

            {
                "host": "<name>",
                "local_path": "<path or empty>",
                "remote_path": "<path or empty>",
                "diff": "<unified diff text>",   # may be empty if equal
                "error": "<msg>",                # only on remote failure
            }

        HTML response: a ``text/html`` body containing a complete
        ``difflib.HtmlDiff().make_file()`` document with a custom
        title. Operators can drop it into an iframe / new tab without
        any further wrapping.

        404 when ``host`` is not in ``[hosts.*]``. Local-side errors
        (no config on disk) degrade to ``local_path = ""`` and
        ``local_text = ""``; the diff is computed against an empty
        local file in that case.
        """
        if format not in ("json", "html"):
            raise HTTPException(
                400,
                f"format must be 'json' or 'html'; got {format!r}",
            )

        host_cfg = config.hosts.get(host)
        if host_cfg is None:
            raise HTTPException(
                404,
                f"host {host!r} is not in [hosts.*] config",
            )

        from harbormaster.config import _config_search_paths
        from harbormaster.plugins import query_remote_config

        local_text = ""
        local_path = ""
        for candidate in _config_search_paths():
            if candidate.is_file():
                local_path = str(candidate)
                try:
                    local_text = candidate.read_text(encoding="utf-8")
                except OSError:
                    local_text = ""
                break

        remote_payload = await asyncio.to_thread(
            query_remote_config, host_cfg
        )
        remote_text = str(remote_payload.get("text") or "")
        remote_path = str(remote_payload.get("path") or "")
        remote_err = remote_payload.get("error")

        from_label = local_path or "<local>"
        to_label = (
            f"{host}:{remote_path}" if remote_path else f"{host}:<remote>"
        )

        if format == "html":
            html_diff = difflib.HtmlDiff(tabsize=4, wrapcolumn=80)
            html = html_diff.make_file(
                local_text.splitlines(),
                remote_text.splitlines(),
                fromdesc=from_label,
                todesc=to_label,
                context=True,
                numlines=3,
            )
            return Response(content=html, media_type="text/html")

        diff = "".join(
            difflib.unified_diff(
                local_text.splitlines(keepends=True),
                remote_text.splitlines(keepends=True),
                fromfile=from_label,
                tofile=to_label,
            )
        )
        out: dict[str, object] = {
            "host": host,
            "local_path": local_path,
            "remote_path": remote_path,
            "diff": diff,
        }
        if remote_err:
            out["error"] = str(remote_err)
        return JSONResponse(content=out)

    # v7.0.0a6: TTL cache for /api/projects.
    # Per-process cache; on a 20+ project install this avoids the
    # filesystem walk + git log + manifest detection on every poll.
    # Signature uses the previously-discovered project dirs so a
    # rename/deletion still invalidates within the TTL window.
    from harbormaster.ui.manifest_cache import (
        ProjectsCache,
        default_persist_path,
        project_dirs_from_infos,
    )

    # v21.0.0a8: persist to ~/.harbormaster/projects_cache.json so the
    # cache is shared with peer harbormaster processes (UI + MCP) and
    # survives a UI restart.
    projects_cache = ProjectsCache(persist_path=default_persist_path())
    # Track the last set of dirs we discovered so the next request can
    # build an mtime signature without re-walking. Empty on first call
    # (so the first hit is always a miss → walk → cache).
    _last_dirs: list[Path] = []

    # v21.0.3 perf: warm `projects_cache` on app startup in a background
    # task so the first user request hits an already-built cache instead
    # of paying ~1 s for `discover_projects()`. Runs in a worker thread
    # so it doesn't delay uvicorn's bind-and-serve. Best-effort — failures
    # log a warning and the first user request just pays the cold cost.
    @app.on_event("startup")
    async def _warm_caches_on_startup() -> None:
        nonlocal _last_dirs
        import asyncio as _asyncio
        import logging as _logging

        _logger = _logging.getLogger("harbormaster.ui.warmup")

        def _prime() -> None:
            nonlocal _last_dirs
            try:
                infos = discover_projects(
                    config.projects, ignore_patterns=config.ignore.patterns,
                )
                _last_dirs = project_dirs_from_infos(infos)

                def _builder() -> list[dict[str, object]]:
                    return [p.as_dict() for p in infos]

                projects_cache.get(_builder, _last_dirs)
                _logger.info(
                    "warmup: primed projects_cache with %d projects",
                    len(infos),
                )
            except Exception as exc:  # noqa: BLE001 — best-effort
                _logger.warning("warmup: prime failed (%s)", exc)

        # Schedule without awaiting — uvicorn must finish startup fast.
        _asyncio.create_task(_asyncio.to_thread(_prime))

    # v21.0.5: user-managed hide list — operator clicks "Hide" in sidebar,
    # the name lands in ~/.harbormaster/user_hidden.json, and /api/projects
    # filters it out from the next response. Separate from [ignore].patterns
    # (TOML config, static, version-controllable) — this is the dynamic
    # per-click sibling.
    from harbormaster.ui.user_hidden import get_default_store as _user_hidden_store

    @app.get("/api/projects")
    async def list_projects() -> list[dict[str, object]]:
        nonlocal _last_dirs

        def _build() -> list[dict[str, object]]:
            nonlocal _last_dirs
            infos = discover_projects(config.projects, ignore_patterns=config.ignore.patterns)
            _last_dirs = project_dirs_from_infos(infos)
            return [p.as_dict() for p in infos]

        # v21.0.3 perf: the cache hit path is sub-ms, but a miss runs
        # `discover_projects()` (~0.9 s for 62 projects post-T3). Offload
        # to a thread so the miss doesn't stall every other /api/* request
        # that wants the event loop.
        rows = await asyncio.to_thread(projects_cache.get, _build, _last_dirs)
        # v21.0.5: filter user_hidden post-cache so toggling Hide/Unhide
        # never invalidates the projects_cache (which is keyed off the
        # set of project directories on disk, not the operator's view).
        hidden = set(_user_hidden_store().list())
        if hidden:
            rows = [r for r in rows if r.get("name") not in hidden]
        return rows

    # v11.0.0a6: 60s TTL memo for /api/ignored-projects. Two
    # discovery passes per call is non-trivial work and the sidebar
    # polls this on every page load; cache the diff for one minute.
    _ignored_cache: dict[str, dict[str, object] | float | None] = {
        "value": None, "cached_at": 0.0,
    }
    _ignored_ttl_s: float = 60.0

    @app.get("/api/ignored-projects")
    async def list_ignored_projects() -> dict[str, object]:
        """v10.0.0a4: surface the projects hidden by `[ignore].patterns`.

        Read-only diagnostic endpoint. Returns:
          - patterns: the configured ignore patterns (echoed for the
            sidebar tooltip).
          - count: integer.
          - names: sorted list of project basenames that would have
            been discovered if `[ignore]` were empty but ARE
            currently hidden.

        Computed by running discovery twice — once with
        `ignore_patterns=[]` and once with the live patterns — and
        diffing. O(2 * discovery cost); 60s TTL memo (v11.0.0a6).
        """
        now_t = time.monotonic()
        raw_cached_at = _ignored_cache.get("cached_at")
        cached_at = (
            float(raw_cached_at) if isinstance(raw_cached_at, int | float) else 0.0
        )
        cached_value = _ignored_cache.get("value")
        if (
            isinstance(cached_value, dict)
            and (now_t - cached_at) < _ignored_ttl_s
        ):
            return cached_value

        # v21.0.3 perf: short-circuit the "no ignore patterns configured"
        # case — the diff between "all" and "visible" is always empty,
        # so a single discovery is enough (and we don't need its result
        # since we only return patterns/count/names).
        if not config.ignore.patterns:
            payload: dict[str, object] = {
                "patterns": [],
                "count": 0,
                "names": [],
            }
            _ignored_cache["value"] = payload
            _ignored_cache["cached_at"] = now_t
            return payload

        # v21.0.3 perf: run the two discovery passes on a worker thread
        # so a cold cache miss (~3 s total) doesn't block the event loop.
        # v21.0.5: exclude user-hidden names from this set — they have
        # their own sidebar section ("Hidden by you"), so listing them
        # here too would double-count and confuse the operator.
        user_hidden = set(_user_hidden_store().list())

        def _compute_ignored() -> dict[str, object]:
            all_names = {
                p.name for p in discover_projects(
                    config.projects, ignore_patterns=[],
                )
            }
            visible_names = {
                p.name for p in discover_projects(
                    config.projects, ignore_patterns=config.ignore.patterns,
                )
            }
            ignored = sorted((all_names - visible_names) - user_hidden)
            return {
                "patterns": list(config.ignore.patterns),
                "count": len(ignored),
                "names": ignored,
            }

        payload = await asyncio.to_thread(_compute_ignored)
        _ignored_cache["value"] = payload
        _ignored_cache["cached_at"] = now_t
        return payload

    # v21.0.5: user-managed hide list — endpoints. POST + DELETE bust
    # the /api/ignored-projects cache because the diff between
    # config-ignored and user-hidden changes whenever a name moves
    # between the two sets.
    class _UserHiddenAdd(BaseModel):
        model_config = ConfigDict(extra="forbid")
        name: str = Field(..., min_length=1, max_length=128)

    @app.get("/api/user-hidden")
    async def list_user_hidden() -> dict[str, object]:
        """Return the operator's per-project hide list."""
        names = _user_hidden_store().list()
        return {"count": len(names), "names": names}

    @app.post("/api/user-hidden")
    async def add_user_hidden(body: _UserHiddenAdd) -> dict[str, object]:
        """Hide a project from the operator's view. Idempotent — adding
        a name that's already hidden returns 200 with `added=False`."""
        try:
            added = _user_hidden_store().add(body.name)
        except ValueError as exc:
            raise HTTPException(400, "invalid project name") from exc
        # Cache-bust: the /api/ignored-projects diff depends on this set.
        _ignored_cache["value"] = None
        _ignored_cache["cached_at"] = 0.0
        return {"name": body.name, "added": added}

    @app.delete("/api/user-hidden/{name}")
    async def remove_user_hidden(name: str) -> dict[str, object]:
        """Unhide a project. Idempotent — removing a name that wasn't
        hidden returns 200 with `removed=False`."""
        # Use the same regex the store enforces, but fail fast on the
        # URL component before touching state.
        from harbormaster.projects import _PROJECT_NAME_RE
        if not _PROJECT_NAME_RE.match(name):
            raise HTTPException(400, "invalid project name")
        removed = _user_hidden_store().remove(name)
        _ignored_cache["value"] = None
        _ignored_cache["cached_at"] = 0.0
        return {"name": name, "removed": removed}

    # ----- v10.0.0a5: per-project memories viewer (read-only) ----------
    # `GET /api/projects/{name}/memories` — list available memory files.
    # `GET /api/projects/{name}/memories/{file}` — return raw markdown.
    # Only `CLAUDE.md` and `.serena/memories/*.md` are served — anything
    # else 400s. Path traversal is also blocked at the file token.

    def _memories_list_for(project_path: Path) -> list[dict[str, object]]:
        out: list[dict[str, object]] = []
        claude = project_path / "CLAUDE.md"
        if claude.is_file():
            st = claude.stat()
            out.append({
                "name": "CLAUDE.md",
                "size": st.st_size,
                "mtime": int(st.st_mtime),
                # v14.0.0a5: YAML frontmatter `tags: [...]` if present.
                "tags": _extract_memory_tags(claude),
            })
        memdir = project_path / ".serena" / "memories"
        if memdir.is_dir():
            for f in sorted(memdir.glob("*.md")):
                if not f.is_file():
                    continue
                st = f.stat()
                out.append({
                    "name": f".serena/memories/{f.name}",
                    "size": st.st_size,
                    "mtime": int(st.st_mtime),
                    "tags": _extract_memory_tags(f),
                })
        return out

    def _extract_memory_tags(path: Path) -> list[str]:
        """v14.0.0a5: parse a ``tags:`` field out of YAML frontmatter.

        Frontmatter shapes we accept (everything else ignored)::

            ---
            tags: [foo, bar, baz]
            ---

        or::

            ---
            tags: ["foo", "bar"]
            ---

        v15.0.0a1: also accept the YAML block-list form::

            ---
            tags:
              - foo
              - bar
            ---

        Reads only the first 4 KiB of the file to bound cost (frontmatter
        always lives at the top). No PyYAML dependency — we look for the
        opening ``---``, then a single ``tags:`` line; if its inline value
        is a JSON-style list we parse it; otherwise we walk subsequent
        lines for ``- item`` block-list entries until indentation breaks.
        Anything more exotic returns an empty list. Failures are silent
        (operator-side feature, never block listing).
        """
        try:
            head = path.read_bytes()[:4096].decode("utf-8", errors="replace")
        except OSError:
            return []
        if not head.startswith("---"):
            return []
        # Frontmatter ends at the next "---" line. Find it.
        end_marker = head.find("\n---", 3)
        if end_marker == -1:
            return []
        block = head[3:end_marker]
        lines = block.splitlines()
        for idx, raw_line in enumerate(lines):
            line = raw_line.strip()
            if not line.lower().startswith("tags:"):
                continue
            value = line[5:].strip()
            if value.startswith("[") and value.endswith("]"):
                inner = value[1:-1]
                tags: list[str] = []
                for tok in inner.split(","):
                    t = tok.strip().strip('"').strip("'")
                    if t:
                        tags.append(t)
                return tags
            if value == "":
                # v15.0.0a1: try YAML block-list form on subsequent lines.
                tags = []
                for follow in lines[idx + 1 :]:
                    stripped = follow.strip()
                    if not stripped:
                        # Blank lines inside the list are allowed by YAML;
                        # we keep going until a non-list line breaks us out.
                        continue
                    if not stripped.startswith("-"):
                        break
                    item = stripped[1:].strip().strip('"').strip("'")
                    if item:
                        tags.append(item)
                return tags
            return []
        return []

    def _memory_path_for(project_path: Path, file_token: str) -> Path:
        """Validate `file_token` and return the absolute path inside
        `project_path`. Raises HTTPException(400) on any traversal or
        unauthorised filename.
        """
        # Block absolute, parent-traversal, and backslashes.
        if not file_token or file_token.startswith("/") or "\\" in file_token:
            raise HTTPException(400, "invalid memory filename")
        if ".." in file_token.split("/"):
            raise HTTPException(400, "invalid memory filename")
        # Allowlist: exact CLAUDE.md, OR `.serena/memories/<basename>.md`
        # where basename matches a strict identifier.
        if file_token == "CLAUDE.md":
            return project_path / "CLAUDE.md"
        if file_token.startswith(".serena/memories/") and file_token.endswith(".md"):
            basename = file_token[len(".serena/memories/"):]
            # Disallow nested slashes inside the basename.
            if "/" in basename or not basename or basename in (".md",):
                raise HTTPException(400, "invalid memory filename")
            # Strict identifier-ish basename (alphanumerics, dot,
            # underscore, hyphen). This is the same shape we accept in
            # `validate_project_name`.
            import re as _re
            stem = basename[:-3]
            if not _re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", stem):
                raise HTTPException(400, "invalid memory filename")
            return project_path / ".serena" / "memories" / basename
        raise HTTPException(400, "invalid memory filename")

    @app.get("/api/projects/{name}/memories")
    async def list_project_memories(name: str) -> dict[str, object]:
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

        return {
            "project": name,
            "files": _memories_list_for(project_path),
        }

    class _MemoryPutBody(BaseModel):
        """v10.0.0a6: body for PUT /api/projects/{name}/memories/{file}."""

        content: str = Field(..., description="raw markdown body")

    class _MemoryPostBody(BaseModel):
        """v10.0.0a6: body for POST /api/projects/{name}/memories.

        `filename` follows the same allowlist as the GET path:
        either exactly `CLAUDE.md` or `.serena/memories/<basename>.md`.
        """

        filename: str = Field(...)
        content: str = Field(...)

    def _atomic_write(target: Path, content: str) -> None:
        """v10.0.0a6: write `content` to `target` via temp file + rename
        so a crash mid-write doesn't leave a partial memory file.

        v21.0.1 (security M2): mode 0o600 — memory files may contain
        Q&A traces / prompts that echo tokens, paths, or otherwise
        sensitive operator context; restrict to owner-only on
        multi-user hosts.
        """
        import contextlib

        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(target.suffix + ".hm-tmp")
        try:
            tmp.write_text(content, encoding="utf-8")
            tmp.replace(target)
            with contextlib.suppress(OSError):
                target.chmod(0o600)
        finally:
            if tmp.exists():
                with contextlib.suppress(OSError):
                    tmp.unlink()

    @app.put("/api/projects/{name}/memories/{file_token:path}")
    async def put_project_memory(
        name: str, file_token: str, body: _MemoryPutBody,
    ) -> dict[str, object]:
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

        target = _memory_path_for(project_path, file_token)
        # Containment check (target may not yet exist on PUT-create).
        try:
            project_resolved = project_path.resolve()
            # If target doesn't exist, resolve its parent for containment.
            anchor = (target if target.exists() else target.parent).resolve()
            anchor.relative_to(project_resolved)
        except (OSError, ValueError) as exc:
            raise HTTPException(400, "invalid memory filename") from exc

        try:
            _atomic_write(target, body.content)
        except OSError as exc:
            raise HTTPException(500, "write failed") from exc

        st = target.stat()
        # v11.0.0a2: append revision row. Best-effort: never block the
        # write response if the revisions DB is misconfigured.
        try:
            from harbormaster.ui.memory_revisions import memory_revisions
            memory_revisions.record(
                project=name, file=file_token,
                content=body.content, saved_at=int(st.st_mtime),
            )
        except Exception:  # noqa: BLE001
            pass
        return {
            "project": name,
            "file": file_token,
            "size": st.st_size,
            "mtime": int(st.st_mtime),
            "created": False,
        }

    @app.post("/api/projects/{name}/memories")
    async def create_project_memory(
        name: str, body: _MemoryPostBody,
    ) -> dict[str, object]:
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

        target = _memory_path_for(project_path, body.filename)

        try:
            project_resolved = project_path.resolve()
            anchor = (target if target.exists() else target.parent).resolve()
            anchor.relative_to(project_resolved)
        except (OSError, ValueError) as exc:
            raise HTTPException(400, "invalid memory filename") from exc

        if target.exists():
            raise HTTPException(409, f"memory file already exists: {body.filename}")

        try:
            _atomic_write(target, body.content)
        except OSError as exc:
            raise HTTPException(500, "write failed") from exc

        st = target.stat()
        # v11.0.0a2: append revision row. Best-effort.
        try:
            from harbormaster.ui.memory_revisions import memory_revisions
            memory_revisions.record(
                project=name, file=body.filename,
                content=body.content, saved_at=int(st.st_mtime),
            )
        except Exception:  # noqa: BLE001
            pass
        return {
            "project": name,
            "file": body.filename,
            "size": st.st_size,
            "mtime": int(st.st_mtime),
            "created": True,
        }

    @app.get("/api/projects/{name}/memories/{file_token:path}")
    async def get_project_memory(
        name: str, file_token: str, render: str | None = None,
    ) -> Response:
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

        target = _memory_path_for(project_path, file_token)
        if not target.is_file():
            raise HTTPException(404, "memory file not found")

        # Belt-and-braces containment check post-resolve to defeat
        # symlinks pointing outside the project root.
        try:
            project_resolved = project_path.resolve()
            target_resolved = target.resolve()
            target_resolved.relative_to(project_resolved)
        except (OSError, ValueError) as exc:
            raise HTTPException(400, "invalid memory filename") from exc

        try:
            text = target.read_text(encoding="utf-8")
        except OSError as exc:
            raise HTTPException(500, "read failed") from exc

        # v11.0.0a3: optional server-side render. `?render=html` returns
        # bleach-sanitised HTML so callers can drop the result straight
        # into the DOM without needing marked.js or trusting the source.
        if render == "html":
            from harbormaster.ui.markdown import render_safe
            html = render_safe(text)
            return Response(
                content=html,
                media_type="text/html; charset=utf-8",
            )

        return Response(content=text, media_type="text/markdown; charset=utf-8")

    # ----- v11.0.0a3: live markdown preview ---------------------------
    # POST /api/render-markdown — accepts {text: <raw markdown>} and
    # returns sanitised HTML. Powers the editor's split-pane preview
    # (300ms debounce on the front end).

    class _RenderMarkdownBody(BaseModel):
        text: str = Field(default="")
        # v15.0.0a6: optional project context — when set, the per-project
        # `<project>/.harbormaster.toml` `[markdown] strict` value is
        # honoured (falling through to the global `[markdown]` setting).
        project: str | None = Field(default=None)

    @app.post("/api/render-markdown")
    async def render_markdown_endpoint(
        body: _RenderMarkdownBody,
    ) -> Response:
        from harbormaster.ui.markdown import render_safe, resolve_markdown_strict

        # v15.0.0a6: per-project markdown strict resolution.
        # No project context → use the global value. Unknown project
        # name → silently fall through to the global value (operator-
        # side feature, never block rendering).
        project_path = None
        if body.project:
            from harbormaster.projects import find_project_path

            try:
                project_path = find_project_path(
                    body.project,
                    config.projects,
                    ignore_patterns=list(config.ignore.patterns),
                )
            except Exception:
                project_path = None
        strict = resolve_markdown_strict(
            project_path=project_path,
            global_strict=config.markdown.strict,
        )
        html = render_safe(body.text, strict=strict)
        return Response(
            content=html,
            media_type="text/html; charset=utf-8",
        )

    # ----- v11.0.0a2: per-file memory revision history -----------------
    # `GET /api/projects/{name}/memory-history?file=<token>` — returns
    # metadata for each saved revision (id + saved_at + bytes_diff,
    # newest first). Content is NOT included; fetch via the per-rev
    # endpoint below.
    # `GET /api/projects/{name}/memory-revisions/{rev_id}?file=<token>`
    # — returns the persisted content of a specific revision.
    # The `?file=` query design avoids path-token collisions with the
    # existing `{file_token:path}` catch-all on the memory viewer.

    @app.get("/api/projects/{name}/memory-history")
    async def get_memory_history(
        name: str, file: str,
    ) -> dict[str, object]:
        from harbormaster.projects import (
            validate_project_name as _validate_project_name,
        )
        from harbormaster.ui.memory_revisions import memory_revisions

        try:
            _validate_project_name(name)
        except ValueError as e:
            raise HTTPException(400, str(e)) from e
        if not file:
            raise HTTPException(400, "?file= is required")

        revs = memory_revisions.history(project=name, file=file)
        return {
            "project": name,
            "file": file,
            "count": len(revs),
            "revisions": [
                {
                    "id": r.id,
                    "saved_at": r.saved_at,
                    "bytes_diff": r.bytes_diff,
                }
                for r in revs
            ],
        }

    @app.get("/api/projects/{name}/memory-revisions/diff")
    async def get_memory_revision_diff(
        name: str, file: str,
        from_: int = Query(..., alias="from"),
        to: int | None = None,
        format: str = "unified",
    ) -> Response:
        """v12.0.0a4: unified-diff endpoint for memory revisions.

        - `?from=<rev_id_a>&to=<rev_id_b>` diffs revision A → revision B
          (both must exist on file).
        - `?from=<rev_id_a>` (no `to`) diffs revision A → the current
          on-disk file content. This is the common operator action:
          "what changed between this revision and now?".

        Output formats (v13.0.0a3):

        - `?format=unified` (default, v12.0.0a4 contract preserved) →
          ``text/plain`` unified diff via ``difflib.unified_diff``.
        - `?format=html` → ``text/html`` side-by-side diff via
          ``difflib.HtmlDiff().make_table`` with line numbers + change
          highlights. Wrapped in a minimal `<style>`-free fragment so
          the dashboard can drop the response body straight into a
          container; the fragment is also bleach-friendly (uses the
          v12.0.0a4 extended allowlist).
        """
        import difflib

        from harbormaster.projects import (
            resolve_project,
        )
        from harbormaster.projects import (
            validate_project_name as _validate_project_name,
        )
        from harbormaster.ui.memory_revisions import memory_revisions

        try:
            _validate_project_name(name)
        except ValueError as e:
            raise HTTPException(400, str(e)) from e
        if not file:
            raise HTTPException(400, "?file= is required")

        rev_from = memory_revisions.get_revision(
            project=name, file=file, rev_id=from_,
        )
        if rev_from is None or rev_from.content is None:
            raise HTTPException(404, "from revision not found")

        if to is not None:
            rev_to = memory_revisions.get_revision(
                project=name, file=file, rev_id=to,
            )
            if rev_to is None or rev_to.content is None:
                raise HTTPException(404, "to revision not found")
            to_content = rev_to.content
            to_label = f"revision {to}"
        else:
            # Diff against current on-disk content.
            try:
                cwd = resolve_project(
                    name, config.projects,
                    ignore_patterns=config.ignore.patterns,
                )
            except ValueError as e:
                raise HTTPException(404, str(e)) from e
            target = (cwd / file).resolve()
            # Stay within the project root (defence against `?file=../`).
            try:
                target.relative_to(cwd.resolve())
            except ValueError as e:
                raise HTTPException(400, "file path escapes project") from e
            try:
                to_content = target.read_text(encoding="utf-8")
            except FileNotFoundError as e:
                raise HTTPException(404, "current file not found") from e
            to_label = "current"

        if format == "html":
            # v13.0.0a3: side-by-side HTML diff. HtmlDiff.make_table
            # emits a <table class="diff">…</table> fragment with
            # change highlights via td.diff_chg / td.diff_add / .diff_sub.
            # We don't include the surrounding <html>/<style> chrome —
            # the dashboard provides its own styles in base.html.
            html_diff = difflib.HtmlDiff(wrapcolumn=80)
            body = html_diff.make_table(
                rev_from.content.splitlines(),
                to_content.splitlines(),
                fromdesc=f"revision {from_}",
                todesc=to_label,
                context=False,
            )
            return Response(
                content=body,
                media_type="text/html; charset=utf-8",
            )
        if format != "unified":
            raise HTTPException(
                400,
                "format must be 'unified' (default) or 'html'",
            )
        diff_lines = difflib.unified_diff(
            rev_from.content.splitlines(keepends=True),
            to_content.splitlines(keepends=True),
            fromfile=f"revision {from_}",
            tofile=to_label,
            lineterm="",
        )
        body = "".join(diff_lines)
        return Response(
            content=body,
            media_type="text/plain; charset=utf-8",
        )

    @app.get("/api/projects/{name}/memory-revisions/{rev_id}")
    async def get_memory_revision(
        name: str, rev_id: int, file: str,
    ) -> Response:
        from harbormaster.projects import (
            validate_project_name as _validate_project_name,
        )
        from harbormaster.ui.memory_revisions import memory_revisions

        try:
            _validate_project_name(name)
        except ValueError as e:
            raise HTTPException(400, str(e)) from e
        if not file:
            raise HTTPException(400, "?file= is required")

        rev = memory_revisions.get_revision(
            project=name, file=file, rev_id=rev_id,
        )
        if rev is None or rev.content is None:
            raise HTTPException(404, "revision not found")
        return Response(
            content=rev.content,
            media_type="text/markdown; charset=utf-8",
        )

    # One ManifestCache per UI process — first hit warm-loads, subsequent
    # /api/graph polls hit the cache and stat the manifest file only.
    graph_cache = ManifestCache()

    # v21.0.2 perf: /api/graph used to block the asyncio event loop for
    # ~2s (lockfile walk across all projects), serialising every other
    # /api/* request behind it on a single-worker uvicorn. Two fixes:
    #
    #   1. compute in a worker thread via asyncio.to_thread, so the
    #      event loop stays responsive while filesystem work happens.
    #   2. TTL cache the payload by (include_dev_deps, transitive,
    #      format). Dependency graphs change on a project add/remove
    #      or manifest edit — slow on the human timescale. 60s TTL
    #      keeps repeated polls (sidebar refresh, autodetect, second
    #      tab) free of any disk work.
    _graph_ttl_s = 60.0
    _graph_payload_cache: dict[
        tuple[bool, bool, str],
        tuple[float, dict[str, object]],
    ] = {}

    def _compute_graph_payload(
        include_dev_deps: bool, transitive: bool, fmt: str,
    ) -> dict[str, object]:
        """Sync builder — called from asyncio.to_thread."""
        manifests = []
        for p in discover_projects(
            config.projects, ignore_patterns=config.ignore.patterns,
        ):
            m = graph_cache.get(Path(p.path))
            if m is not None:
                manifests.append(m)
        graph = build_graph(
            manifests,
            include_dev_deps=include_dev_deps,
            transitive=transitive,
        )
        payload: dict[str, object] = {
            "projects_discovered": len(manifests),
            "projects_with_lockfile": sum(
                1 for m in manifests if m.lockfile is not None
            ),
            "manifests": [m.as_dict() for m in manifests],
            "graph": graph.as_dict(),
            "mermaid": graph_to_mermaid(graph),
        }
        if fmt == "cytoscape":
            payload["cytoscape"] = _graph_to_cytoscape(graph)
        return payload

    @app.get("/api/graph")
    async def api_graph(
        include_dev_deps: bool = False,
        transitive: bool = False,
        format: str = "mermaid",
    ) -> dict[str, object]:
        """Cross-project graph + ready-to-render mermaid markup.

        v2.1.0a1: surfaces the v2.0.0a1 `transitive` toggle so the
        dashboard can let the user flip between manifest-only and
        lockfile-resolved deps.

        v21.0.0a9: optional `?format=cytoscape` adds a `cytoscape`
        field carrying nodes/edges in Cytoscape elements shape, so the
        dashboard can render with Cytoscape (force-directed) instead
        of the static Mermaid block. The `mermaid` field is always
        emitted for backwards compat.

        v21.0.2 perf: TTL cached (60s) + computed in a worker thread.
        """
        key = (include_dev_deps, transitive, format)
        now = time.monotonic()
        cached = _graph_payload_cache.get(key)
        if cached is not None and (now - cached[0]) < _graph_ttl_s:
            return cached[1]
        payload = await asyncio.to_thread(
            _compute_graph_payload, include_dev_deps, transitive, format,
        )
        _graph_payload_cache[key] = (now, payload)
        return payload

    @app.get("/api/kpi")
    async def api_kpi(since_seconds: int = 3600) -> dict[str, object]:
        """KPI strip aggregator (v8.0.0a5).

        Returns the 5 numbers the dashboard's top strip displays in
        a single round-trip so the UI doesn't have to fan out 5
        polls. Cheap — projects count uses the v7.0.0a6 cache,
        recent-queries count is a covering-index scan, reembed
        state and bridge state are already in-memory.

        Soft-fails per cell — a missing [history] extra returns
        `{recent_queries: null, ...}` rather than 500ing the whole
        endpoint. Operators always see *some* numbers.
        """
        nonlocal _last_dirs

        # Projects count — reuse the same cache the project list uses.
        def _build_for_count() -> list[dict[str, object]]:
            nonlocal _last_dirs
            infos = discover_projects(config.projects, ignore_patterns=config.ignore.patterns)
            _last_dirs = project_dirs_from_infos(infos)
            return [p.as_dict() for p in infos]

        # v21.0.3 perf: same thread-offload as /api/projects above.
        projects = await asyncio.to_thread(
            projects_cache.get, _build_for_count, _last_dirs,
        )

        # Reembed state — same source of truth as /api/history/state.
        reembed_phase: str | None = None
        reembed_processed: int | None = None
        reembed_total: int | None = None
        if config.history.enabled:
            try:
                from harbormaster.history import read_reembed_state

                state = read_reembed_state()
                reembed_phase = state.phase
                reembed_processed = state.processed
                reembed_total = state.total
            except ImportError:
                pass

        # Recent queries — sum across hosts is overkill for v8.0.0a5;
        # local-only is the dashboard's primary surface and the v9
        # waterfall surface will surface multi-host counts separately.
        recent_queries: int | None = None
        if config.history.enabled:
            try:
                from harbormaster.history import (
                    QAStore,
                    get_embedding_backend,
                )

                backend = get_embedding_backend(config)
                store = QAStore.open(
                    db_dir=config.history.db_dir,
                    host=None,
                    embedding_backend=backend,
                    embedding_dim=config.history.embedding_dim,
                )
                try:
                    cutoff = int(time.time() - max(60, since_seconds))
                    recent_queries = store.count_since(cutoff)
                finally:
                    store.close()
            except (ImportError, Exception):  # noqa: BLE001 — soft-fail
                recent_queries = None

        # Bridge — same shape as /api/bridge/status's status pill.
        bridge_state = "disabled"
        if config.fleetq.enabled:
            import os as _os
            api_token_present = bool(
                _os.environ.get(config.fleetq.api_token_env, "").strip()
            )
            # Runtime detail lives in /api/bridge/status; here we
            # only need a coarse pill state.
            bridge_state = "configured" if api_token_present else "token missing"

        # Dispatcher — v9.0.0a2: derive a coarse pill state from the
        # live counters now exposed by /api/dispatcher/status. The
        # KPI-strip cell stays a single string for backwards-compat
        # (existing template binds plain text); operators who want the
        # full counters point at /api/dispatcher/status directly.
        dispatcher_state = "ready"
        try:
            from harbormaster.fleetq import get_dispatcher_stats

            stats = get_dispatcher_stats().snapshot()
            active = int(stats.get("active_workers", 0))
            if active > 0:
                dispatcher_state = f"{active} active"
            else:
                # Surface failure-rate when no work is in flight: if
                # the most recent dispatches all failed, the operator
                # should see something other than "idle".
                tools = stats.get("tools", {})
                if isinstance(tools, dict) and tools:
                    total_done = sum(
                        int(v.get("total_completed", 0))
                        + int(v.get("total_failed", 0))
                        for v in tools.values()
                        if isinstance(v, dict)
                    )
                    dispatcher_state = "idle" if total_done > 0 else "ready"
        except ImportError:
            pass

        return {
            "projects": len(projects),
            "active_embeds": {
                "phase": reembed_phase,
                "processed": reembed_processed,
                "total": reembed_total,
            },
            "recent_queries": recent_queries,
            "since_seconds": since_seconds,
            "bridge": bridge_state,
            "dispatcher": dispatcher_state,
        }

    @app.get("/api/kpi/history")
    async def api_kpi_history() -> dict[str, list[int]]:
        """v21.0.0a7: 24-hour sparkline history for each numeric KPI cell.

        Returns 24 hourly buckets (oldest → newest) for the four
        sparkline-enabled cells on the dashboard KPI strip. Cheap —
        the only non-trivial query is one COUNT-per-hour scan against
        the network_log mcp_calls table (covering index on `timestamp`).

        Soft-fails per series — a missing [history] extra or empty
        network log just returns zero-arrays so the SVG still renders
        a flat line rather than a broken cell.
        """
        nonlocal _last_dirs

        now_s = int(time.time())
        # 24 buckets, oldest first. Each bucket is `[start_ms, end_ms)`.
        hour_starts = [now_s - (i * 3600) for i in range(23, -1, -1)]

        # Projects — stable count from the same cache /api/projects uses.
        def _build_for_count() -> list[dict[str, object]]:
            nonlocal _last_dirs
            infos = discover_projects(
                config.projects,
                ignore_patterns=config.ignore.patterns,
            )
            _last_dirs = project_dirs_from_infos(infos)
            return [p.as_dict() for p in infos]

        try:
            # v21.0.3 perf: thread-offload like /api/projects + /api/kpi.
            proj_count = len(
                await asyncio.to_thread(
                    projects_cache.get, _build_for_count, _last_dirs,
                )
            )
        except Exception:  # noqa: BLE001 — soft-fail to zero
            proj_count = 0
        projects_hist = [proj_count] * 24

        # Recent queries — bucketed COUNT against network_log (mcp_calls).
        # network_log timestamps are epoch-MS; convert hour boundaries.
        recent_queries_hist: list[int] = [0] * 24
        try:
            from harbormaster.ui.network_log import network_log

            for i, start_s in enumerate(hour_starts):
                end_s = start_s + 3600
                # Inclusive-start, exclusive-end. network_log.stats() takes
                # `since_ms` but not an upper bound; do a direct SQL count.
                row = network_log._conn.execute(  # noqa: SLF001 — internal API
                    "SELECT COUNT(*) FROM mcp_calls "
                    "WHERE timestamp >= ? AND timestamp < ?",
                    (start_s * 1000, end_s * 1000),
                ).fetchone()
                recent_queries_hist[i] = int(row[0]) if row else 0
        except Exception:  # noqa: BLE001 — soft-fail
            recent_queries_hist = [0] * 24

        # Active embeds + host budget — no historical persistence layer
        # exists for these yet; return zero arrays so the sparkline cell
        # renders a flat line (acceptable per spec).
        active_embeds_hist = [0] * 24
        host_budget_hist = [0] * 24

        return {
            "projects": projects_hist,
            "active_embeds": active_embeds_hist,
            "recent_queries": recent_queries_hist,
            "host_budget": host_budget_hist,
        }

    @app.get("/health")
    async def fleetq_health() -> dict[str, str]:
        """Alias of /api/health using the path FleetQ Bridge expects when
        pinging an HTTP-tunnel-mode connection."""
        return {"status": "ok", "version": __version__}

    @app.get("/discover")
    async def fleetq_discover() -> dict[str, object]:
        """FleetQ Bridge HTTP-tunnel-mode validation endpoint."""
        try:
            from harbormaster.fleetq import build_manifest
        except ImportError:
            return {"agents": [], "llm_endpoints": [], "mcp_servers": []}
        return build_manifest()

    @app.get("/agent-card/{project_name}")
    async def agent_card(
        project_name: str, request: Request,
    ) -> dict[str, Any]:
        """A2A v0.3 Agent Card per project.

        Each `~/htdocs/<project>` configured under [projects] gets its
        own card describing the skills harbormaster offers against it
        (ask + delegate, both read-only in v1). Cards are intentionally
        per-project rather than per-tool: the MCP wire underneath has
        one server with N tools; the A2A wire wants one card per
        addressable agent. Mapping convention: the MCP "project" axis
        is the A2A "agent" axis.

        Schema reference: https://github.com/google/A2A
        Implementation: a subset that's stable across A2A v0.3.x —
        we don't claim capabilities we can't actually serve.
        """
        projects = {p.name: p for p in discover_projects(config.projects, ignore_patterns=config.ignore.patterns)}
        project = projects.get(project_name)
        if project is None:
            raise HTTPException(404, f"unknown project: {project_name!r}")

        # Best-effort base URL — useful when this card is served behind
        # a reverse proxy and the relative `/mcp/harbormaster` path is
        # not enough for A2A consumers that need an absolute invocation
        # URL. Falls back to a relative path if the request didn't
        # carry a Host header (programmatic test client).
        host_header = request.headers.get("host")
        base_url = (
            f"http://{host_header}" if host_header else ""
        )
        invocation_url = f"{base_url}/mcp/harbormaster"

        description = project.brief or (
            f"Harbormaster project: {project_name}. "
            "Spawn a Claude Code subagent inside the project's directory "
            "and answer questions or delegate read-only tasks."
        )

        return {
            "schemaVersion": "0.3.0",
            "name": f"harbormaster.{project_name}",
            "description": description,
            "url": invocation_url,
            "skills": [
                {
                    "id": f"ask-{project_name}",
                    "name": "Ask",
                    "description": (
                        f"Ask the {project_name} project's subagent a "
                        "question. Returns a markdown summary under "
                        "500 words. Streams partial output via SSE "
                        "when invoked with Accept: text/event-stream."
                    ),
                    "tags": ["read", "claude-code", "streaming"],
                    "inputModes": ["text/plain"],
                    "outputModes": ["text/event-stream", "application/json"],
                },
                {
                    "id": f"delegate-{project_name}",
                    "name": "Delegate",
                    "description": (
                        f"Delegate a task to the {project_name} subagent. "
                        "Pass allow_writes=true to authorise edits "
                        "(the subagent applies them directly and returns "
                        "a change-summary); allow_writes=false (default) "
                        "keeps it read-only and the subagent returns a "
                        "plan. Streams partial output via SSE when invoked "
                        "with Accept: text/event-stream."
                    ),
                    "tags": ["claude-code", "streaming"],
                    "inputModes": ["text/plain"],
                    "outputModes": ["text/event-stream", "application/json"],
                },
                {
                    "id": f"status-{project_name}",
                    "name": "Status",
                    "description": (
                        f"Recent git log, Serena memories, and log tails "
                        f"for the {project_name} project."
                    ),
                    "tags": ["read", "diagnostic"],
                    "inputModes": ["text/plain"],
                    "outputModes": ["application/json"],
                },
            ],
            "capabilities": {
                "streaming": True,
                "stateTransitionHistory": False,
                "pushNotifications": False,
            },
            "defaultInputModes": ["text/plain"],
            "defaultOutputModes": ["text/event-stream", "application/json"],
            "metadata": {
                "harbormaster": {
                    "version": __version__,
                    "project_path": project.path,
                    "has_serena": project.has_serena,
                    "has_claude_md": project.has_claude_md,
                },
            },
        }

    @app.post("/mcp/{server}")
    async def mcp_proxy(
        server: str,
        body: McpProxyRequest,
        request: Request,
    ) -> Any:
        """HTTP-direct MCP routing (FleetQ HTTP-tunnel-mode receive side).

        Accepts the same payload shape as agent-fleet's BridgeController::mcpCall
        validate() block: {request_id?, method, params, timeout?}. Looks up the
        named tool in the FastMCP tool registry (passed into create_app via
        the `mcp` kwarg) and returns an MCP-style result envelope.

        Streaming: when the client sends `Accept: text/event-stream`, the
        response is an SSE stream that emits periodic `heartbeat` events
        while the tool runs (so reverse proxies don't time out long calls
        like ask_project / delegate_task / fan_out_ask) and a final
        `result` (or `error`) event with the same envelope JSON-mode would
        return. JSON mode (default Accept) is fully unchanged.

        404 when:
          - {server} != 'harbormaster'
          - create_app was called without an mcp instance (UI-only mode)
        """
        if server != "harbormaster":
            raise HTTPException(404, f"unknown MCP server: {server!r}")
        if mcp is None:
            raise HTTPException(
                404,
                "MCP HTTP-direct routing not available — harbormaster-ui was "
                "started without an MCP server bound. Run harbormaster-mcp "
                "alongside, or update your launcher to pass mcp=build_server(config).",
            )

        # v11.0.0a1: caller-project propagation. When the HTTP-tunnel
        # client (e.g. agent-fleet's BridgeController) declares which
        # project owns the originating session, record that as the
        # network event's caller. Falls back to "operator" when the
        # header is absent, matching pre-v11 behaviour.
        caller_header = request.headers.get("x-caller-project", "").strip()
        caller = caller_header or None

        accept = request.headers.get("accept", "")
        if "text/event-stream" in accept.lower():
            return EventSourceResponse(
                _stream_dispatch(mcp, body, config, caller=caller),
            )

        return _dispatch_mcp(mcp, body, caller=caller)


async def _stream_dispatch(
    mcp: Any,
    body: McpProxyRequest,
    config: HarbormasterConfig | None = None,
    *,
    caller: str | None = None,
) -> AsyncIterator[dict[str, str]]:
    """SSE event generator for the streaming `/mcp/{server}` path.

    Two paths:

    1. `ask_project` / `delegate_task` against a local OR SSH project:
       bypass FastMCP's sync tool dispatch and call
       `ClaudeBackend.ask_local_stream` / `ask_remote_stream` directly,
       emitting each yielded text delta as a `chunk` event. The final
       `result` event carries the assembled string for callers that
       want a single terminal payload.

    2. Everything else: dispatch through FastMCP's sync tool registry,
       emit `heartbeat` events every `_HEARTBEAT_INTERVAL_S` seconds
       while it runs, then emit the final envelope as a `result` or
       `error` event.

    Event shapes (data is JSON-encoded for every event):
      heartbeat → {"elapsed_ms": <int>}
      chunk     → {"text": <str>}
      result    → <MCP envelope, identical to JSON-mode response body>
      error     → {"status": <int>, "detail": <str>}

    `fan_out_ask` falls through to path 2 today — it's a parallel
    multi-project call and needs chunk multiplexing semantics that
    don't exist yet.
    """
    if (
        config is not None
        and body.method == "tools/call"
        and isinstance(body.params, dict)
    ):
        tool_name = body.params.get("name")
        args = body.params.get("arguments")
        if tool_name in _STREAMING_TOOLS and isinstance(args, dict):
            prompt_builder = _STREAMING_TOOLS[tool_name]
            host = args.get("host")
            if host in (None, "local"):
                async for evt in _stream_local_tool(
                    config, args, prompt_builder,
                    max_turns_default=5, caller=caller,
                ):
                    yield evt
                return
            if isinstance(host, str) and host:
                async for evt in _stream_remote_tool(
                    config, args, host, prompt_builder,
                    max_turns_default=5, caller=caller,
                ):
                    yield evt
                return

    start = time.monotonic()
    task = asyncio.create_task(
        asyncio.to_thread(_dispatch_mcp, mcp, body, caller=caller),
    )
    # v9.0.0a4: per-stream monotonic event id. EventSource records the
    # most recent id as `lastEventId`; on reconnect the browser sends it
    # back as `Last-Event-ID`. The /mcp/* path is request-scoped so
    # resumption isn't useful (the call is gone by then) but the id
    # field is part of the protocol contract for typed events.
    next_id = _StreamIdSeq()

    # v11.0.0a7: per-surface heartbeat tuning. Streaming defaults to
    # 5s (proxy-keepalive critical) but can be overridden via
    # [server] heartbeat_interval_streaming_s.
    streaming_heartbeat = (
        config.server.heartbeat_interval_streaming_s
        if config is not None
        else _HEARTBEAT_INTERVAL_S
    )
    while not task.done():
        try:
            await asyncio.wait_for(
                asyncio.shield(task), timeout=streaming_heartbeat,
            )
        except TimeoutError:
            elapsed_ms = int((time.monotonic() - start) * 1000)
            yield {
                "event": "heartbeat",
                "id": next_id.next(),
                "data": json.dumps({"elapsed_ms": elapsed_ms}),
            }
        except BaseException:  # noqa: BLE001 — task raised, post-loop handles it
            # When the wrapped task raises, wait_for re-raises here. We
            # break out of the heartbeat loop and let the post-loop
            # `task.result()` re-raise into our error handlers, which
            # render the failure as an in-band SSE event instead of
            # propagating up Starlette's exception middleware (which
            # would try to send a fresh response on a stream that has
            # already started).
            break

    try:
        result = task.result()
    except HTTPException as e:
        yield {
            "event": "error",
            "id": next_id.next(),
            "data": json.dumps({"status": e.status_code, "detail": e.detail}),
        }
        return
    except Exception as e:  # noqa: BLE001 — surface any error as SSE event
        yield {
            "event": "error",
            "id": next_id.next(),
            "data": json.dumps(
                {"status": 500, "detail": f"{type(e).__name__}: {e}"}
            ),
        }
        return

    yield {"event": "result", "id": next_id.next(), "data": json.dumps(result)}


PromptBuilder = Callable[[dict[str, Any]], str]
"""A prompt builder takes the tool's `arguments` dict and returns the
full prompt to send to the backend, OR raises ValueError with a
caller-readable message if a required argument is missing/invalid.
Tool-specific framing (e.g. delegate_task's read-only injunction)
lives in the builder, not in the streaming dispatch."""


def _ask_project_prompt(arguments: dict[str, Any]) -> str:
    question = arguments.get("question")
    if not isinstance(question, str) or not question:
        raise ValueError("params.arguments.question (string) is required")
    return (
        f"{question}\n\n"
        "Return a concise markdown summary under 500 words. "
        "Focus on the answer; skip unnecessary preamble."
    )


def _delegate_task_prompt(arguments: dict[str, Any]) -> str:
    task = arguments.get("task")
    deliverable = arguments.get("deliverable")
    if not isinstance(task, str) or not task:
        raise ValueError("params.arguments.task (string) is required")
    if not isinstance(deliverable, str) or not deliverable:
        raise ValueError("params.arguments.deliverable (string) is required")
    if arguments.get("allow_writes"):
        # v22.0.0a1: caller-authorised writes. Subagent edits files
        # directly and returns a change-summary; bypassPermissions is
        # already enabled at the backend layer so the prompt is what
        # gates behaviour.
        suffix = (
            "You may edit files in this project. Make the change directly, "
            "then return a markdown summary under 500 words listing: "
            "(1) files changed with one-line reasons, "
            "(2) any new tests added, "
            "(3) follow-ups left for the operator. "
            "Do NOT git commit — the operator will review and commit."
        )
    else:
        suffix = (
            "Read-only mode. Do NOT edit files. "
            "Report what you would do and which files you would touch. "
            "Return markdown under 500 words."
        )
    return f"Task: {task}\n\nDeliverable: {deliverable}\n\n{suffix}"


_STREAMING_TOOLS: dict[str, PromptBuilder] = {
    "ask_project": _ask_project_prompt,
    "delegate_task": _delegate_task_prompt,
}
"""Map of MCP tool name → prompt builder for tools that emit chunk
events. Anything not in this map falls through to the heartbeat path
(unchanged from a13)."""


def _validate_max_turns(arguments: dict[str, Any], default: int) -> int:
    """Resolve and validate max_turns. Raises ValueError on bad values."""
    max_turns = arguments.get("max_turns", default)
    if not isinstance(max_turns, int) or max_turns <= 0:
        raise ValueError("params.arguments.max_turns must be a positive int")
    return max_turns


def _resolve_model_arg(arguments: dict[str, Any]) -> str | None:
    """v21.0.0a10: pull the optional ``model`` arg from MCP tool args.

    Accepts a non-empty string (treated as alias or full id by the
    backend's `_resolve_model`) or None. Empty string / missing key
    is normalised to None so the backend default applies.
    """
    raw = arguments.get("model")
    if raw is None:
        return None
    if not isinstance(raw, str):
        raise ValueError("params.arguments.model must be a string or null")
    stripped = raw.strip()
    return stripped or None


async def _stream_local_tool(
    config: HarbormasterConfig,
    arguments: dict[str, Any],
    prompt_builder: PromptBuilder,
    *,
    max_turns_default: int,
    caller: str | None = None,
) -> AsyncIterator[dict[str, str]]:
    """Generic local-streaming SSE dispatcher.

    Steps:
      1. Validate `name` (project) — raise 400 on missing/empty.
      2. Build the prompt via `prompt_builder` — tool-specific. Raises
         ValueError on missing tool args; surfaced as 400.
      3. Validate `max_turns`.
      4. Eagerly construct the backend iterator via
         `make_local_backend_stream`. ValueError (project lookup) → 400;
         BackendError(config) → 400; BackendError(other) → 502 lazily.
      5. Iterate, emitting one `chunk` event per text delta, then a
         final `result` event with the assembled string.

    Failure modes are all in-band SSE error events — no HTTP-level
    error after the response has started.
    """
    project_name = arguments.get("name")
    if not isinstance(project_name, str) or not project_name:
        yield {
            "event": "error",
            "data": json.dumps(
                {"status": 400, "detail": "params.arguments.name (string) is required"}
            ),
        }
        return

    try:
        full_prompt = prompt_builder(arguments)
        max_turns = _validate_max_turns(arguments, max_turns_default)
        model = _resolve_model_arg(arguments)
    except ValueError as e:
        yield {
            "event": "error",
            "data": json.dumps({"status": 400, "detail": str(e)}),
        }
        return

    from harbormaster.tools._helpers import make_local_backend_stream

    try:
        sync_iter = make_local_backend_stream(
            project_name=project_name, prompt=full_prompt,
            max_turns=max_turns, config=config, model=model,
        )
    except ValueError as e:
        yield {
            "event": "error",
            "data": json.dumps(
                {"status": 400, "detail": f"ValueError: {e}"}
            ),
        }
        return
    except BackendError as e:
        # v21.0.0a10: model_not_allowed is a client-side error
        # (operator picked a model that's not in the whitelist).
        status = 400 if e.code in ("config_error", "model_not_allowed") else 502
        yield {
            "event": "error",
            "data": json.dumps(
                {"status": status, "detail": f"BackendError({e.code}): {e}"}
            ),
        }
        return

    async for evt in _emit_chunks_then_result(
        sync_iter,
        record_ctx={
            "config": config,
            "project_name": project_name,
            "host": None,
            "prompt": full_prompt,
            "tool": _tool_name_for_builder(prompt_builder),
            "caller": caller,
        },
    ):
        yield evt


async def _stream_remote_tool(
    config: HarbormasterConfig,
    arguments: dict[str, Any],
    host: str,
    prompt_builder: PromptBuilder,
    *,
    max_turns_default: int,
    caller: str | None = None,
) -> AsyncIterator[dict[str, str]]:
    """SSH counterpart to `_stream_local_tool`. Identical structure
    modulo the make_remote_backend_stream call + host parameter."""
    project_name = arguments.get("name")
    if not isinstance(project_name, str) or not project_name:
        yield {
            "event": "error",
            "data": json.dumps(
                {"status": 400, "detail": "params.arguments.name (string) is required"}
            ),
        }
        return

    try:
        full_prompt = prompt_builder(arguments)
        max_turns = _validate_max_turns(arguments, max_turns_default)
        model = _resolve_model_arg(arguments)
    except ValueError as e:
        yield {
            "event": "error",
            "data": json.dumps({"status": 400, "detail": str(e)}),
        }
        return

    from harbormaster.tools._helpers import make_remote_backend_stream

    try:
        sync_iter = make_remote_backend_stream(
            project_name=project_name, prompt=full_prompt,
            max_turns=max_turns, host=host, config=config, model=model,
        )
    except ValueError as e:
        yield {
            "event": "error",
            "data": json.dumps(
                {"status": 400, "detail": f"ValueError: {e}"}
            ),
        }
        return
    except BackendError as e:
        # v21.0.0a10: model_not_allowed is a client-side error
        # (operator picked a model that's not in the whitelist).
        status = 400 if e.code in ("config_error", "model_not_allowed") else 502
        yield {
            "event": "error",
            "data": json.dumps(
                {"status": status, "detail": f"BackendError({e.code}): {e}"}
            ),
        }
        return

    async for evt in _emit_chunks_then_result(
        sync_iter,
        record_ctx={
            "config": config,
            "project_name": project_name,
            "host": host,
            "prompt": full_prompt,
            "tool": _tool_name_for_builder(prompt_builder),
            "caller": caller,
        },
    ):
        yield evt


def _tool_name_for_builder(builder: PromptBuilder) -> str:
    """Reverse-lookup the registered tool name for a builder.

    v10.0.0a1: needed by the streaming dispatcher to forward a
    semantically correct `tool` label into `_maybe_record_qa` so that
    Recent Q&A rows match the sync-path schema.
    """
    for name, b in _STREAMING_TOOLS.items():
        if b is builder:
            return name
    return "unknown"


async def _emit_chunks_then_result(
    sync_iter: Any,
    *,
    record_ctx: dict[str, Any] | None = None,
) -> AsyncIterator[dict[str, str]]:
    """Drive a sync iterator from an async generator, emitting one
    `chunk` event per yielded text delta and a final `result` event
    with the assembled string. Mid-iteration `BackendError` becomes
    a 502 error event.

    PEP 479 / asyncio gotcha: StopIteration cannot be marshalled
    across the asyncio.to_thread Future boundary. Convert to a
    sentinel value so the asyncio side detects end-of-iter without
    ever propagating StopIteration through a Future.

    v9.0.0a4: every emitted event carries a per-stream monotonic
    SSE ``id`` so the browser's EventSource records ``lastEventId``.

    v9.0.0a5: every text delta emits BOTH a legacy ``chunk`` event
    (data = ``{"text": ...}``) AND a typed ``token`` event
    (data = ``{"delta": ...}``). A final ``usage`` event with
    best-effort counters precedes the terminal ``result`` event.

    v10.0.0a2: legacy ``chunk`` event REMOVED. Only ``token`` is
    emitted per text delta. Clients that still listen for ``chunk``
    will get nothing — they must migrate to ``token`` (data.delta).
    Backwards-compat cycle was one minor version (deprecated in
    v9.0.0a5, removed in v10.0.0a2).
    """
    chunks: list[str] = []
    sentinel = object()
    next_id = _StreamIdSeq()
    start_monotonic = time.monotonic()

    def _next_or_sentinel() -> Any:
        try:
            return next(sync_iter)
        except StopIteration:
            return sentinel

    while True:
        try:
            chunk = await asyncio.to_thread(_next_or_sentinel)
        except BackendError as e:
            # v21.0.7: mid-stream BackendError needs the same forensic
            # treatment as the sync `run_backend` path — log a
            # structured warning + mirror to network_log so the
            # dashboard Activity tab shows the failure. Generate a
            # correlation id so the agent's error event matches the
            # log line + db row.
            from harbormaster.tools._helpers import (
                _new_correlation_id,
                _record_backend_failure,
            )

            cid = _new_correlation_id()
            elapsed_ms = int((time.monotonic() - start_monotonic) * 1000)
            if record_ctx is not None:
                # Instrumentation must never break the in-flight error
                # response — _record_backend_failure already swallows
                # internally, but suppress here as a belt-and-braces.
                with contextlib.suppress(Exception):
                    _record_backend_failure(
                        project_name=str(record_ctx["project_name"]),
                        host=record_ctx.get("host"),
                        prompt=str(record_ctx["prompt"]),
                        tool=str(record_ctx["tool"]),
                        error=e,
                        elapsed_ms=elapsed_ms,
                        correlation_id=cid,
                    )
            yield {
                "event": "error",
                "id": next_id.next(),
                "data": json.dumps(
                    {
                        "status": 502,
                        "detail": f"BackendError({e.code}): {e}",
                        "correlation_id": cid,
                        "elapsed_ms": elapsed_ms,
                    }
                ),
            }
            return
        except (ValueError, FileNotFoundError) as e:
            yield {
                "event": "error",
                "id": next_id.next(),
                "data": json.dumps(
                    {"status": 400, "detail": f"{type(e).__name__}: {e}"}
                ),
            }
            return
        if chunk is sentinel:
            break
        chunks.append(chunk)
        # v10.0.0a2: only the typed `token` event is emitted now.
        # The legacy `chunk` event was deprecated in v9.0.0a5 and
        # removed here. Clients consume `token.delta` exclusively.
        yield {
            "event": "token",
            "id": next_id.next(),
            "data": json.dumps({"delta": chunk}),
        }

    # v11.0.0a5: real backend-reported usage when available, with a
    # graceful fall-back to the v9.0.0a5 chunk-count approximation
    # for backends / claude versions that don't surface a usage block
    # in their stream-json output.
    real_usage = getattr(sync_iter, "usage", None)
    if real_usage is not None and getattr(real_usage, "has_real_usage", False):
        usage_payload: dict[str, object] = {
            "input_tokens": int(getattr(real_usage, "input_tokens", 0)),
            "output_tokens": int(getattr(real_usage, "output_tokens", 0)),
            "cache_creation_input_tokens": int(
                getattr(real_usage, "cache_creation_input_tokens", 0),
            ),
            "cache_read_input_tokens": int(
                getattr(real_usage, "cache_read_input_tokens", 0),
            ),
            "model": getattr(real_usage, "model", None),
            "output_chunks": len(chunks),
            "output_chars": sum(len(c) for c in chunks),
            # `approximate` flag DROPPED when the backend reports real
            # counts (v11.0.0a5 deliverable).
        }
    else:
        usage_payload = {
            "output_chunks": len(chunks),
            "output_chars": sum(len(c) for c in chunks),
            "approximate": True,
        }
    yield {
        "event": "usage",
        "id": next_id.next(),
        "data": json.dumps(usage_payload),
    }

    assembled = "".join(chunks)

    # v10.0.0a1: bug fix — Recent Q&A was empty for streamed calls.
    # Sync `run_backend` calls `_maybe_record_qa`; streaming dispatcher
    # didn't. Mirror the same write-back here so the dashboard,
    # fan-out, and project-detail surfaces (all streaming-path) populate
    # the local sqlite history store. Failures are swallowed inside
    # `_maybe_record_qa` (matches sync-path semantics).
    if record_ctx is not None and assembled:
        duration_ms = int((time.monotonic() - start_monotonic) * 1000)
        try:
            from harbormaster.tools._helpers import _maybe_record_qa

            _maybe_record_qa(
                config=record_ctx["config"],
                project_name=record_ctx["project_name"],
                host=record_ctx["host"],
                prompt=record_ctx["prompt"],
                answer=assembled,
                tool=record_ctx["tool"],
                duration_ms=duration_ms,
            )
        except Exception:  # noqa: BLE001 — never break the stream
            pass

    # v10.0.0a7: record one network event per completed streamed call.
    # The caller is "operator" today (no parent-project context for
    # UI-direct calls); a future v11 deferred decoration could pass
    # the originating project when a delegated tool calls another
    # tool. Failures swallowed — instrumentation must never break
    # the stream.
    if record_ctx is not None:
        try:
            from harbormaster.ui.network_log import network_log

            network_log.record(
                caller=str(record_ctx.get("caller") or "operator"),
                target=str(record_ctx["project_name"]),
                tool=str(record_ctx["tool"]),
                status="ok" if assembled else "error",
                question_preview=str(record_ctx["prompt"]),
                # v21.0.8: persist the full request body so the
                # chat tab can lazy-fetch it on row expand.
                question_full=str(record_ctx["prompt"]),
            )
        except Exception:  # noqa: BLE001
            pass

    envelope = {
        "result": {
            "content": [{"type": "text", "text": assembled}],
        },
    }
    yield {"event": "result", "id": next_id.next(), "data": json.dumps(envelope)}


def _dispatch_mcp(
    mcp: Any, body: McpProxyRequest, *, caller: str | None = None,
) -> dict[str, Any]:
    """Translate body.method + body.params into a tool call against
    FastMCP's tool manager and return an MCP JSON-RPC-shaped response."""
    if body.method == "tools/list":
        return {
            "result": {
                "tools": [
                    {
                        "name": t.name,
                        "description": getattr(t, "description", "") or "",
                    }
                    for t in mcp._tool_manager.list_tools()
                ]
            }
        }

    # tools/call
    name = body.params.get("name")
    if not isinstance(name, str) or not name:
        raise HTTPException(400, "params.name (string) is required for tools/call")
    arguments = body.params.get("arguments") or {}
    if not isinstance(arguments, dict):
        raise HTTPException(400, "params.arguments must be an object")

    tool = next(
        (t for t in mcp._tool_manager.list_tools() if t.name == name),
        None,
    )
    if tool is None:
        raise HTTPException(404, f"tool not found: {name!r}")

    try:
        result = tool.fn(**arguments)
    except TypeError as e:
        raise HTTPException(400, f"tool argument error: {e}") from e
    except Exception as e:  # noqa: BLE001 - propagate as MCP error envelope
        # v10.0.0a7: record the failed call too (status=error).
        try:
            from harbormaster.ui.network_log import network_log
            _record_mcp_dispatch(
                network_log, name, arguments,
                status="error", caller=caller,
            )
        except Exception:  # noqa: BLE001
            pass
        return {
            "result": {
                "isError": True,
                "content": [
                    {"type": "text", "text": f"{type(e).__name__}: {e}"}
                ],
            }
        }

    # v10.0.0a7: instrument the legacy heartbeat-path tools too —
    # recall_qa, fan_out_ask, project_status, etc. Streaming-path
    # tools (ask_project, delegate_task) are recorded inside
    # `_emit_chunks_then_result` instead.
    try:
        from harbormaster.ui.network_log import network_log
        _record_mcp_dispatch(
            network_log, name, arguments, status="ok", caller=caller,
        )
    except Exception:  # noqa: BLE001
        pass

    return {"result": {"content": [_serialize_tool_result(result)]}}


def _record_mcp_dispatch(
    network_log: Any,
    tool_name: str,
    arguments: dict[str, Any],
    *,
    status: str,
    caller: str | None = None,
) -> None:
    """v10.0.0a7: route a single tool/call into the network log.

    For `fan_out_ask` we record one event per resolved target so
    each fan-out leg appears as a distinct edge in the graph. For
    everything else, a single event with `target = arguments.name`
    (or "operator" if absent — e.g. recall_qa with host="all").

    v11.0.0a1: `caller` defaults to "operator" when absent. When the
    HTTP-tunnel client passed an `X-Caller-Project` header, the
    routing layer threads the project name through; the network log
    then surfaces a real cross-project edge in the graph.
    """
    if tool_name in {"ask_project", "delegate_task"}:
        # Already recorded inside the streaming dispatcher.
        return
    args_target = arguments.get("name") or arguments.get("project")
    question = (
        arguments.get("question")
        or arguments.get("task")
        or arguments.get("query")
        or ""
    )
    preview = question if isinstance(question, str) else ""
    caller_name = caller or "operator"
    # v21.0.8: ``preview`` here is actually the FULL question text
    # (network_store.record applies the 200-char cap on the preview
    # column itself). Pass it as both kwargs so the chat tab's row
    # expand can lazy-fetch the untrimmed body.
    if tool_name == "fan_out_ask":
        projects = arguments.get("projects") or []
        if isinstance(projects, list) and projects:
            for proj in projects:
                if not isinstance(proj, str) or not proj:
                    continue
                network_log.record(
                    caller=caller_name, target=proj,
                    tool=tool_name, status=status,
                    question_preview=preview,
                    question_full=preview,
                )
            return
        # No project list → record an aggregate event so the chat
        # view still shows the fan-out happened.
        network_log.record(
            caller=caller_name, target="(all)",
            tool=tool_name, status=status,
            question_preview=preview,
            question_full=preview,
        )
        return
    network_log.record(
        caller=caller_name,
        target=str(args_target) if isinstance(args_target, str) else "(unknown)",
        tool=tool_name,
        status=status,
        question_preview=preview,
        question_full=preview,
    )


def _serialize_tool_result(result: Any) -> dict[str, Any]:
    """MCP tool results land as `content` entries — text for strings, JSON
    serialization for everything else."""
    if isinstance(result, str):
        return {"type": "text", "text": result}
    try:
        return {"type": "text", "text": json.dumps(result, default=str)}
    except (TypeError, ValueError):
        return {"type": "text", "text": str(result)}

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
import json
import time
from collections.abc import AsyncIterator, Callable
from importlib import resources
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
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


class McpProxyRequest(BaseModel):
    """Body schema for POST /mcp/{server} — mirrors agent-fleet's
    BridgeController::mcpCall validate() shape."""

    request_id: str | None = None
    method: str = Field(pattern="^(tools/call|tools/list)$")
    params: dict[str, Any] = Field(default_factory=dict)
    timeout: int | None = None


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
        project_names = sorted(p.name for p in discover_projects(config.projects))
        host_labels = ["local", *sorted(config.hosts.keys())]
        return _render(
            request,
            "fan_out.html",
            {
                "project_names": project_names,
                "host_labels": host_labels,
            },
        )

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
                (p.as_dict() for p in discover_projects(config.projects)
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

    @app.post("/api/history/reembed")
    async def api_history_reembed_trigger() -> dict[str, object]:
        """v6.0.0a1: manually trigger an auto-reembed run.

        Idempotent: returns 409 when one is already in progress
        (prevents double-click + cross-tab races from spawning
        two threads).
        """
        try:
            from harbormaster.history import trigger_manual_reembed
        except ImportError:
            raise HTTPException(
                503,
                "[history] extra not installed; install with "
                "`pip install harbormaster-mcp[history]`",
            ) from None

        started, error = trigger_manual_reembed(config)
        if not started:
            # 409 for "already running"; 400 for everything else
            # (history disabled / config issue)
            status = 409 if error and "already in progress" in error else 400
            raise HTTPException(status, error or "could not start reembed")
        return {"started": True}

    @app.get("/api/history/state")
    async def api_history_state() -> dict[str, object]:
        """v4.0.0a5: report the auto-reembed runner's current phase.

        Reads the cross-process state file written by the background
        thread (when ``[history] auto_reembed_on_drift = true``). Returns
        an idle snapshot when the file is absent or the thread never
        started.
        """
        try:
            from harbormaster.history import read_reembed_state

            state = read_reembed_state()
            return {
                "available": True,
                "phase": state.phase,
                "processed": state.processed,
                "total": state.total,
                "current_host": state.current_host,
                "started_at": state.started_at,
                "finished_at": state.finished_at,
                "error": state.error,
                "writer_pid": state.writer_pid,
                # v7.0.0a3: surface the cancel flag so the UI can
                # render a 'cancelling…' badge between user click
                # and worker acknowledgment.
                "cancel_requested": state.cancel_requested,
                "auto_reembed_enabled": config.history.auto_reembed_on_drift,
            }
        except ImportError:
            return {
                "available": False,
                "phase": "idle",
                "auto_reembed_enabled": False,
            }

    @app.get("/api/history/reembed/runs")
    async def api_history_reembed_runs() -> dict[str, object]:
        """v7.0.0a4: rolling log of completed reembed runs.

        Returns ``{"runs": [...]}`` where each entry is a
        ReembedRunRecord (started_at, finished_at, total, succeeded,
        failed, cancelled, model). Capped at the most recent
        MAX_HISTORY_RECORDS (50) runs. Returns ``{"runs": []}`` when
        the [history] extra is not installed or the file is missing.
        """
        try:
            from harbormaster.history import read_reembed_runs
        except ImportError:
            return {"runs": []}
        runs = read_reembed_runs()
        return {"runs": [r.model_dump(mode="json") for r in runs]}

    @app.post("/api/history/reembed/cancel")
    async def api_history_reembed_cancel() -> dict[str, object]:
        """v7.0.0a3: request cooperative cancel of a running reembed.

        Idempotent: cancelling a non-running reembed is a no-op that
        returns 200 with ``{"running": false, "cancel_requested": false}``.
        When a run IS in progress, the cancel flag is set in the state
        file; the worker observes it between hosts and exits with
        ``phase = "cancelled"``. The flag does NOT abort an in-flight
        host's reembed (a single host is the smallest atomic unit).
        """
        try:
            from harbormaster.history import request_reembed_cancel
        except ImportError:
            raise HTTPException(
                503,
                "[history] extra not installed; install with "
                "`pip install harbormaster-mcp[history]`",
            ) from None

        was_running, state = request_reembed_cancel()
        return {
            "running": was_running,
            "cancel_requested": state.cancel_requested,
            "phase": state.phase,
        }

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
    async def api_plugins() -> dict[str, object]:
        """Plugin discovery + status (v2.1.0a1).

        Mirrors `harbormaster-mcp plugins list` for browser consumption.
        Each entry point is categorized:

          - "loaded"          : enabled + dist in allowlist + ep discovered
          - "not-allowlisted" : enabled + ep discovered but dist not in allowlist
          - "disabled"        : ep discovered but [plugins].enabled = false
          - "no-dist-name"    : ep present but legacy metadata
          - "missing"         : dist in allowlist but NO ep discovered
        """
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

    # v7.0.0a6: TTL cache for /api/projects.
    # Per-process cache; on a 20+ project install this avoids the
    # filesystem walk + git log + manifest detection on every poll.
    # Signature uses the previously-discovered project dirs so a
    # rename/deletion still invalidates within the TTL window.
    from harbormaster.ui.manifest_cache import (
        ProjectsCache,
        project_dirs_from_infos,
    )

    projects_cache = ProjectsCache()
    # Track the last set of dirs we discovered so the next request can
    # build an mtime signature without re-walking. Empty on first call
    # (so the first hit is always a miss → walk → cache).
    _last_dirs: list[Path] = []

    @app.get("/api/projects")
    async def list_projects() -> list[dict[str, object]]:
        nonlocal _last_dirs

        def _build() -> list[dict[str, object]]:
            nonlocal _last_dirs
            infos = discover_projects(config.projects)
            _last_dirs = project_dirs_from_infos(infos)
            return [p.as_dict() for p in infos]

        return projects_cache.get(_build, _last_dirs)

    # One ManifestCache per UI process — first hit warm-loads, subsequent
    # /api/graph polls hit the cache and stat the manifest file only.
    graph_cache = ManifestCache()

    @app.get("/api/graph")
    async def api_graph(
        include_dev_deps: bool = False,
        transitive: bool = False,
    ) -> dict[str, object]:
        """Cross-project graph + ready-to-render mermaid markup.

        v2.1.0a1: surfaces the v2.0.0a1 `transitive` toggle so the
        dashboard can let the user flip between manifest-only and
        lockfile-resolved deps.
        """
        from pathlib import Path

        manifests = []
        for p in discover_projects(config.projects):
            m = graph_cache.get(Path(p.path))
            if m is not None:
                manifests.append(m)
        graph = build_graph(
            manifests,
            include_dev_deps=include_dev_deps,
            transitive=transitive,
        )
        return {
            "projects_discovered": len(manifests),
            "projects_with_lockfile": sum(
                1 for m in manifests if m.lockfile is not None
            ),
            "manifests": [m.as_dict() for m in manifests],
            "graph": graph.as_dict(),
            "mermaid": graph_to_mermaid(graph),
        }

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
            infos = discover_projects(config.projects)
            _last_dirs = project_dirs_from_infos(infos)
            return [p.as_dict() for p in infos]

        projects = projects_cache.get(_build_for_count, _last_dirs)

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

        # Dispatcher — placeholder until v9 waterfall ships. Always
        # `ready` for now (matches the v8 plan's "or hard-coded
        # 'ready' until v9 waterfall ships" provision).
        dispatcher_state = "ready"

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
        projects = {p.name: p for p in discover_projects(config.projects)}
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
                        f"Delegate a read-only task to the {project_name} "
                        "subagent. v1 fails closed when allow_writes=true; "
                        "the subagent reports what it would do without "
                        "actually editing files. Streams partial output "
                        "via SSE when invoked with Accept: "
                        "text/event-stream."
                    ),
                    "tags": ["read", "claude-code", "streaming"],
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

        accept = request.headers.get("accept", "")
        if "text/event-stream" in accept.lower():
            return EventSourceResponse(_stream_dispatch(mcp, body, config))

        return _dispatch_mcp(mcp, body)


async def _stream_dispatch(
    mcp: Any, body: McpProxyRequest, config: HarbormasterConfig | None = None,
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
                    config, args, prompt_builder, max_turns_default=5,
                ):
                    yield evt
                return
            if isinstance(host, str) and host:
                async for evt in _stream_remote_tool(
                    config, args, host, prompt_builder, max_turns_default=5,
                ):
                    yield evt
                return

    start = time.monotonic()
    task = asyncio.create_task(asyncio.to_thread(_dispatch_mcp, mcp, body))

    while not task.done():
        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=_HEARTBEAT_INTERVAL_S)
        except TimeoutError:
            elapsed_ms = int((time.monotonic() - start) * 1000)
            yield {
                "event": "heartbeat",
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
            "data": json.dumps({"status": e.status_code, "detail": e.detail}),
        }
        return
    except Exception as e:  # noqa: BLE001 — surface any error as SSE event
        yield {
            "event": "error",
            "data": json.dumps(
                {"status": 500, "detail": f"{type(e).__name__}: {e}"}
            ),
        }
        return

    yield {"event": "result", "data": json.dumps(result)}


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
        raise ValueError(
            "delegate_task with allow_writes=true is disabled in v1; "
            "use ask_project for read-only questions"
        )
    return (
        f"Task: {task}\n\n"
        f"Deliverable: {deliverable}\n\n"
        "Read-only mode. Do NOT edit files. "
        "Report what you would do and which files you would touch. "
        "Return markdown under 500 words."
    )


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


async def _stream_local_tool(
    config: HarbormasterConfig,
    arguments: dict[str, Any],
    prompt_builder: PromptBuilder,
    *,
    max_turns_default: int,
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
            max_turns=max_turns, config=config,
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
        status = 400 if e.code == "config_error" else 502
        yield {
            "event": "error",
            "data": json.dumps(
                {"status": status, "detail": f"BackendError({e.code}): {e}"}
            ),
        }
        return

    async for evt in _emit_chunks_then_result(sync_iter):
        yield evt


async def _stream_remote_tool(
    config: HarbormasterConfig,
    arguments: dict[str, Any],
    host: str,
    prompt_builder: PromptBuilder,
    *,
    max_turns_default: int,
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
            max_turns=max_turns, host=host, config=config,
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
        status = 400 if e.code == "config_error" else 502
        yield {
            "event": "error",
            "data": json.dumps(
                {"status": status, "detail": f"BackendError({e.code}): {e}"}
            ),
        }
        return

    async for evt in _emit_chunks_then_result(sync_iter):
        yield evt


async def _emit_chunks_then_result(
    sync_iter: Any,
) -> AsyncIterator[dict[str, str]]:
    """Drive a sync iterator from an async generator, emitting one
    `chunk` event per yielded text delta and a final `result` event
    with the assembled string. Mid-iteration `BackendError` becomes
    a 502 error event.

    PEP 479 / asyncio gotcha: StopIteration cannot be marshalled
    across the asyncio.to_thread Future boundary. Convert to a
    sentinel value so the asyncio side detects end-of-iter without
    ever propagating StopIteration through a Future.
    """
    chunks: list[str] = []
    sentinel = object()

    def _next_or_sentinel() -> Any:
        try:
            return next(sync_iter)
        except StopIteration:
            return sentinel

    while True:
        try:
            chunk = await asyncio.to_thread(_next_or_sentinel)
        except BackendError as e:
            yield {
                "event": "error",
                "data": json.dumps(
                    {"status": 502, "detail": f"BackendError({e.code}): {e}"}
                ),
            }
            return
        except (ValueError, FileNotFoundError) as e:
            yield {
                "event": "error",
                "data": json.dumps(
                    {"status": 400, "detail": f"{type(e).__name__}: {e}"}
                ),
            }
            return
        if chunk is sentinel:
            break
        chunks.append(chunk)
        yield {"event": "chunk", "data": json.dumps({"text": chunk})}

    envelope = {
        "result": {
            "content": [{"type": "text", "text": "".join(chunks)}],
        },
    }
    yield {"event": "result", "data": json.dumps(envelope)}


def _dispatch_mcp(mcp: Any, body: McpProxyRequest) -> dict[str, Any]:
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
        return {
            "result": {
                "isError": True,
                "content": [
                    {"type": "text", "text": f"{type(e).__name__}: {e}"}
                ],
            }
        }

    return {"result": {"content": [_serialize_tool_result(result)]}}


def _serialize_tool_result(result: Any) -> dict[str, Any]:
    """MCP tool results land as `content` entries — text for strings, JSON
    serialization for everything else."""
    if isinstance(result, str):
        return {"type": "text", "text": result}
    try:
        return {"type": "text", "text": json.dumps(result, default=str)}
    except (TypeError, ValueError):
        return {"type": "text", "text": str(result)}

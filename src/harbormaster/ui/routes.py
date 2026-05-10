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

from fastapi import FastAPI, HTTPException, Query, Request
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

    @app.get("/network", response_class=HTMLResponse)
    async def network_page(request: Request) -> HTMLResponse:
        """v10.0.0a7: inter-project network graph view.

        Renders Cytoscape from the vendored `/static/vendor/cytoscape.min.js`
        and feeds it the recent MCP-call events from the in-process
        ring buffer (see `harbormaster.ui.network_log`). New events
        stream in via `/api/network/stream` SSE.
        """
        return _render(request, "network.html", {})

    @app.get("/api/network/events")
    async def list_network_events(limit: int = 500) -> dict[str, object]:
        from harbormaster.ui.network_log import network_log

        if limit < 1 or limit > 5000:
            raise HTTPException(400, "limit must be between 1 and 5000")
        events = network_log.recent(limit=limit)
        return {
            "count": len(events),
            "events": [e.as_dict() for e in events],
        }

    @app.get("/api/network/stats")
    async def network_stats(window: str = "24h") -> dict[str, object]:
        """v11.0.0a6: aggregate metrics over the last 1h / 24h / 7d.

        Query param `window` accepts: ``1h``, ``24h``, ``7d``, ``all``
        (default ``24h``). Returns total_calls, by_tool counts, top
        5 target projects by call count, and the error rate.
        """
        from harbormaster.ui.network_log import network_log

        windows_ms: dict[str, int | None] = {
            "1h": 60 * 60 * 1000,
            "24h": 24 * 60 * 60 * 1000,
            "7d": 7 * 24 * 60 * 60 * 1000,
            "all": None,
        }
        if window not in windows_ms:
            raise HTTPException(
                400, "window must be one of: 1h, 24h, 7d, all",
            )
        delta = windows_ms[window]
        since_ms: int | None = None
        if delta is not None:
            since_ms = int(time.time() * 1000) - delta
        stats = network_log.stats(since_ms=since_ms)
        return {"window": window, **stats}

    @app.get("/api/network/stream")
    async def stream_network_events() -> EventSourceResponse:
        """SSE stream of new MCPCallLog events as they're recorded.

        Subscribers receive an `event: event` frame per new entry
        plus a periodic heartbeat so intermediate proxies don't
        idle-time-out the connection.

        v11.0.0a7: heartbeat cadence configurable via
        ``[server] heartbeat_interval_network_s``. Default 30s
        (events are infrequent, frequent heartbeats are pure noise).
        """
        from harbormaster.ui.network_log import network_log

        heartbeat_s = config.server.heartbeat_interval_network_s

        async def gen() -> AsyncIterator[dict[str, str]]:
            queue = network_log.subscribe()
            try:
                while True:
                    try:
                        ev = await asyncio.wait_for(
                            queue.get(),
                            timeout=heartbeat_s,
                        )
                    except TimeoutError:
                        yield {"event": "heartbeat", "data": "{}"}
                        continue
                    yield {
                        "event": "event",
                        "data": json.dumps(ev.as_dict()),
                    }
            finally:
                network_log.unsubscribe(queue)

        return EventSourceResponse(gen())

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

    @app.get("/dispatcher", response_class=HTMLResponse)
    async def dispatcher_page(request: Request) -> HTMLResponse:
        """v9.0.0a3: trace waterfall surface.

        Single-page view of live + recent dispatcher activity. The page
        consumes ``GET /api/dispatcher/trace`` (SSE) for live spans and
        ``GET /api/dispatcher/recent`` for the last-N completed spans
        on first paint.
        """
        return _render(request, "dispatcher_trace.html", {})

    @app.get("/api/dispatcher/recent")
    async def api_dispatcher_recent(limit: int = 20) -> dict[str, object]:
        """v9.0.0a3: most-recently completed dispatcher spans.

        Bounded by the singleton's ring buffer (currently 100 spans).
        Returns up to ``limit`` (clamped to [1, 100]).
        """
        try:
            from harbormaster.fleetq import get_dispatcher_stats
        except ImportError:
            return {"spans": []}
        clamped = max(1, min(int(limit), 100))
        return {"spans": get_dispatcher_stats().recent_completed(clamped)}

    @app.get("/api/dispatcher/trace")
    async def api_dispatcher_trace(request: Request) -> EventSourceResponse:
        """v9.0.0a3: live span_start/span_end SSE stream.

        Each event's ``data`` is a JSON object with the span shape
        documented in ``DispatcherStats.subscribe`` — at minimum
        ``{kind, span_id, tool, project, started_at, [ended_at, ok]}``.
        Heartbeats every ``_HEARTBEAT_INTERVAL_S`` seconds keep the
        connection alive through nginx/Cloudflare 60s idle timeouts.

        v9.0.0a4: each event carries an SSE ``id`` field equal to the
        event's `span_id` (process-monotonic). On reconnect, clients
        SHOULD send a ``Last-Event-ID`` header carrying the highest
        `span_id` they have already processed; the server replays any
        completed spans with `span_id > last` from the ring buffer
        before resuming the live tail.
        """
        # v9.0.0a4: parse the Last-Event-ID header. EventSource sends it
        # automatically on reconnect; the value is the most-recent SSE
        # event id the client successfully processed.
        last_event_id_raw = request.headers.get("last-event-id")
        last_event_id: int = 0
        if last_event_id_raw:
            try:
                last_event_id = max(0, int(last_event_id_raw))
            except ValueError:
                last_event_id = 0

        async def gen() -> AsyncIterator[dict[str, str]]:
            try:
                from harbormaster.fleetq import get_dispatcher_stats
            except ImportError:
                yield {"event": "ready", "data": json.dumps({"available": False})}
                return
            stats = get_dispatcher_stats()
            sub = stats.subscribe()
            yield {
                "event": "ready",
                "data": json.dumps(
                    {"available": True, "resumed_from": last_event_id}
                ),
            }
            # v9.0.0a4: replay missed completed spans from the ring
            # buffer before resuming the live tail. Cheap — the buffer
            # is at most 100 entries.
            if last_event_id > 0:
                for span in stats.recent_completed(limit=100):
                    if int(span["span_id"]) <= last_event_id:
                        continue
                    yield {
                        "event": "span_end",
                        "id": str(span["span_id"]),
                        "data": json.dumps(
                            {
                                "span_id": span["span_id"],
                                "tool": span["tool"],
                                "project": span["project"],
                                "started_at": span["started_at"],
                                "ended_at": span["ended_at"],
                                "ok": span["ok"],
                            }
                        ),
                    }
            last_heartbeat = time.time()
            try:
                while True:
                    if await request.is_disconnected():
                        break
                    events = sub.drain()
                    for ev in events:
                        kind = ev.pop("kind")
                        # v9.0.0a4: every event carries id = span_id
                        # so the browser's EventSource records it as
                        # the lastEventId for the next reconnect.
                        yield {
                            "event": kind,
                            "id": str(ev.get("span_id", "")),
                            "data": json.dumps(ev),
                        }
                    if events:
                        last_heartbeat = time.time()
                    elif (
                        time.time() - last_heartbeat
                        >= config.server.heartbeat_interval_trace_s
                    ):
                        yield {
                            "event": "heartbeat",
                            "data": json.dumps({"ts": time.time()}),
                        }
                        last_heartbeat = time.time()
                    await asyncio.sleep(0.1)
            finally:
                stats.unsubscribe(sub)

        return EventSourceResponse(gen())

    @app.get("/api/dispatcher/status")
    async def api_dispatcher_status() -> dict[str, object]:
        """Live runtime metrics for the in-process MCP dispatcher (v9.0.0a2).

        Replaces the v8.0.0a5 KPI placeholder ``"ready"`` with a real
        counters payload so the dashboard's KPI strip + the v9 trace
        waterfall can both read from the same source.

        Schema:
        ```
        {
          "running": [{"tool": str, "project": str | null, "started_at": float}, ...],
          "active_workers": int,         # sum of in_flight across tools
          "queue_depth": int,            # always 0 for in-process dispatcher
          "last_dispatched_at": float | null,
          "tools": {
            "<tool_name>": {"in_flight": int, "total_completed": int, "total_failed": int},
            ...
          }
        }
        ```

        The endpoint is always available — when the [fleetq] extra is
        absent the import fails and the response is the canonical
        empty shape (zero counters across the board).
        """
        try:
            from harbormaster.fleetq import get_dispatcher_stats
        except ImportError:
            return {
                "running": [],
                "active_workers": 0,
                "queue_depth": 0,
                "last_dispatched_at": None,
                "tools": {},
            }
        return get_dispatcher_stats().snapshot()

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

    @app.get("/api/history/reembed/runs/diff")
    async def api_history_reembed_runs_diff(
        from_: int = Query(..., alias="from"),
        to: int = Query(...),
    ) -> dict[str, object]:
        """v13.0.0a3: parity with memory-revision diff — compare two
        completed reembed runs by index.

        Indices are zero-based offsets into the chronological list
        returned by ``/api/history/reembed/runs`` (``from`` and ``to``
        must both fall within that list). The response is a per-field
        delta dict so the dashboard can render a compact "what
        changed between these two runs" panel without re-deriving
        differences client-side.

        Shape::

            {
                "from_index": 3,
                "to_index": 7,
                "from": <ReembedRunRecord dict>,
                "to": <ReembedRunRecord dict>,
                "delta": {
                    "duration_seconds": 12.4,  # to.finished_at - to.started_at - (...)
                    "total":     +5,
                    "succeeded": +3,
                    "failed":    -1,
                    "cancelled":  0,
                    "model_changed": false
                }
            }

        Returns 404 when either index is out of range, 503 when the
        ``[history]`` extra isn't installed.
        """
        try:
            from harbormaster.history import read_reembed_runs
        except ImportError:
            raise HTTPException(
                503,
                "[history] extra not installed; install with "
                "`pip install harbormaster-mcp[history]`",
            ) from None
        runs = read_reembed_runs()
        if from_ < 0 or from_ >= len(runs):
            raise HTTPException(404, f"from index {from_} out of range")
        if to < 0 or to >= len(runs):
            raise HTTPException(404, f"to index {to} out of range")
        a = runs[from_]
        b = runs[to]
        delta = {
            "duration_seconds": (b.finished_at - b.started_at)
            - (a.finished_at - a.started_at),
            "total": b.total - a.total,
            "succeeded": b.succeeded - a.succeeded,
            "failed": b.failed - a.failed,
            "cancelled": b.cancelled - a.cancelled,
            "model_changed": (a.model or "") != (b.model or ""),
        }
        return {
            "from_index": from_,
            "to_index": to,
            "from": a.model_dump(mode="json"),
            "to": b.model_dump(mode="json"),
            "delta": delta,
        }

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
            infos = discover_projects(config.projects, ignore_patterns=config.ignore.patterns)
            _last_dirs = project_dirs_from_infos(infos)
            return [p.as_dict() for p in infos]

        return projects_cache.get(_build, _last_dirs)

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
        ignored = sorted(all_names - visible_names)
        payload: dict[str, object] = {
            "patterns": list(config.ignore.patterns),
            "count": len(ignored),
            "names": ignored,
        }
        _ignored_cache["value"] = payload
        _ignored_cache["cached_at"] = now_t
        return payload

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
                })
        return out

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
        so a crash mid-write doesn't leave a partial memory file. Mode
        0o644 — readable by group/other since memories aren't secrets,
        but only the owner can edit them via the file system."""
        import contextlib

        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(target.suffix + ".hm-tmp")
        try:
            tmp.write_text(content, encoding="utf-8")
            tmp.replace(target)
            with contextlib.suppress(OSError):
                target.chmod(0o644)
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

    @app.post("/api/render-markdown")
    async def render_markdown_endpoint(
        body: _RenderMarkdownBody,
    ) -> Response:
        from harbormaster.ui.markdown import render_safe
        html = render_safe(body.text)
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
        for p in discover_projects(config.projects, ignore_patterns=config.ignore.patterns):
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
            infos = discover_projects(config.projects, ignore_patterns=config.ignore.patterns)
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
            yield {
                "event": "error",
                "id": next_id.next(),
                "data": json.dumps(
                    {"status": 502, "detail": f"BackendError({e.code}): {e}"}
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
                )
            return
        # No project list → record an aggregate event so the chat
        # view still shows the fan-out happened.
        network_log.record(
            caller=caller_name, target="(all)",
            tool=tool_name, status=status,
            question_preview=preview,
        )
        return
    network_log.record(
        caller=caller_name,
        target=str(args_target) if isinstance(args_target, str) else "(unknown)",
        tool=tool_name,
        status=status,
        question_preview=preview,
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

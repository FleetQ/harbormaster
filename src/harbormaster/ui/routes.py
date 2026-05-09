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
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from harbormaster import __version__
from harbormaster.backends.base import BackendError
from harbormaster.config import HarbormasterConfig
from harbormaster.projects import discover_projects

# Heartbeat cadence for SSE streams. Module-level so tests can monkeypatch
# it down to keep the suite fast. Production value is 5s — short enough to
# beat the typical 60s nginx / Cloudflare idle-read timeout, long enough
# that a fast-finishing tool sees zero heartbeat overhead.
_HEARTBEAT_INTERVAL_S: float = 5.0


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
) -> None:
    @app.get("/", response_class=HTMLResponse)
    async def dashboard(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(
            request,
            "dashboard.html",
            {"version": __version__},
        )

    @app.get("/api/health")
    async def api_health() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    @app.get("/api/projects")
    async def list_projects() -> list[dict[str, object]]:
        return [p.as_dict() for p in discover_projects(config.projects)]

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

"""FleetQ Bridge `agent.request` → MCP tool dispatcher.

v3.0.0a1: closes the publish-surface loop opened by v2.0.0a7. The
relay's `ChunkHandler` accepts the agent.request payload and yields
text chunks; this module is the canonical handler that maps the
request to a local FastMCP tool call and serializes the response.

Wire shape (from `docs/fleetq-relay-protocol.md`):

    payload = {
        "request_id": "<uuid>",
        "server": "harbormaster",
        "method": "tools/call" | "tools/list",
        "params": {...},          # for tools/call: {"name": str, "arguments": dict}
        "timeout": <int>,         # advisory only — local dispatch is in-process
    }

The dispatcher yields exactly one chunk: a JSON-encoded MCP-style
response envelope, e.g.

    {"result": {"content": [{"type": "text", "text": "..."}]}}
    {"result": {"tools": [{"name": "...", "description": "..."}, ...]}}
    {"result": {"isError": true, "content": [{"type": "text", "text": "<msg>"}]}}

The relay's `_dispatch_chunk_handler` wraps each chunk in a
`client-relay.chunk` event (final sentinel `done=true` follows
automatically). FleetQ-side `popChunk` concatenates chunks, so a
single-chunk envelope is fine for tool responses.

Validation errors (bad method, missing params, unknown tool) become
`isError: true` envelopes — surfaced to FleetQ as a normal MCP error
result, NOT as a `client-relay.error`. Truly internal failures (e.g.
a tool implementation raising) also become `isError: true`. The
relay-level `client-relay.error` path is reserved for the dispatcher
itself crashing on a malformed payload.
"""
from __future__ import annotations

import contextlib
import json
import logging
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


SERVER_NAME = "harbormaster"


# v9.0.0a2: per-tool runtime counters for the dispatcher.
# Exposed via GET /api/dispatcher/status (UI route) and consumed by
# the dispatcher CLI when running against an HTTP server.
#
# All mutations go through DispatcherStats; the lock guards both the
# per-tool counters dict and the active-running-spans list. Read
# methods snapshot under the lock so the consumer never observes a
# torn dict.
@dataclass
class _ToolCounters:
    in_flight: int = 0
    total_completed: int = 0
    total_failed: int = 0


@dataclass
class _RunningSpan:
    tool: str
    project: str | None
    started_at: float  # epoch seconds


class DispatcherStats:
    """Thread-safe live metrics for the in-process MCP dispatcher.

    Designed for low overhead — every call to ``dispatch`` mutates
    two counters and ~once per call walks a small list. There's no
    background thread, no persistent storage; on process restart the
    counters reset. That's acceptable for a sidecar-metrics endpoint
    whose primary consumer is a 30s-polling KPI strip.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._tools: dict[str, _ToolCounters] = {}
        self._running: list[_RunningSpan] = []
        self._last_dispatched_at: float | None = None

    def record_start(self, tool: str, project: str | None = None) -> _RunningSpan:
        """Note that a tool dispatch has begun. Returns the span the
        caller must pass back to ``record_end``."""
        span = _RunningSpan(tool=tool, project=project, started_at=time.time())
        with self._lock:
            counters = self._tools.setdefault(tool, _ToolCounters())
            counters.in_flight += 1
            self._running.append(span)
        return span

    def record_end(self, span: _RunningSpan, *, ok: bool) -> None:
        """Note that a previously-started dispatch has ended."""
        with self._lock:
            counters = self._tools.setdefault(span.tool, _ToolCounters())
            counters.in_flight = max(0, counters.in_flight - 1)
            if ok:
                counters.total_completed += 1
            else:
                counters.total_failed += 1
            # Concurrent reset() between start and end can drop the span
            # ahead of us — counters still update; running list is best-effort.
            with contextlib.suppress(ValueError):
                self._running.remove(span)
            self._last_dispatched_at = time.time()

    def snapshot(self) -> dict[str, Any]:
        """Capture a consistent point-in-time view of the current state.

        Shape mirrors the v9.0.0a2 ``/api/dispatcher/status`` schema:
        ``{running: [...], active_workers: int, queue_depth: int,
        last_dispatched_at: float | None, tools: {name: {...}}}``.
        ``queue_depth`` is always 0 for the in-process dispatcher;
        the field is preserved so consumers don't have to special-case
        the in-process vs. pool-backed deployment.
        """
        with self._lock:
            running = [
                {
                    "tool": s.tool,
                    "project": s.project,
                    "started_at": s.started_at,
                }
                for s in self._running
            ]
            tools = {
                name: {
                    "in_flight": c.in_flight,
                    "total_completed": c.total_completed,
                    "total_failed": c.total_failed,
                }
                for name, c in self._tools.items()
            }
            active_workers = sum(c.in_flight for c in self._tools.values())
            return {
                "running": running,
                "active_workers": active_workers,
                "queue_depth": 0,
                "last_dispatched_at": self._last_dispatched_at,
                "tools": tools,
            }

    def reset(self) -> None:
        """Clear all counters. Test helper — production code never calls this."""
        with self._lock:
            self._tools.clear()
            self._running.clear()
            self._last_dispatched_at = None


# Process-wide singleton. Tests can grab it via ``get_dispatcher_stats``
# and call ``reset`` between cases; production code should never hold
# a reference longer than a single dispatch.
_STATS = DispatcherStats()


def get_dispatcher_stats() -> DispatcherStats:
    return _STATS

# v5.0.0a3: tools verified safe to run concurrently under the v4.0.0a6
# dispatcher pool. Operators with custom plugin tools should add them
# to this set explicitly OR list them under [fleetq] dispatcher_unsafe_tools
# to keep them on the single-worker path.
#
# All current first-party tools passed the v5.0.0a2 fake-claude stress;
# read-only tools are inherently safe; backend-invoking tools were proven
# safe by the 50-concurrent stress test. Any future tool that holds
# process-global state (e.g. a write-side cache) must be added to the
# operator's unsafe list until proven otherwise.
SAFE_FOR_PARALLEL: frozenset[str] = frozenset({
    # read-only
    "list_projects",
    "list_hosts",
    "project_status",
    "project_graph",
    "recall_qa",
    # backend-invoking (subprocess-isolated)
    "ask_project",
    "delegate_task",
    "fan_out_ask",
})


def is_tool_safe_for_parallel(
    payload: dict[str, Any],
    *,
    unsafe_tools: frozenset[str] | None = None,
) -> bool:
    """Decide whether a given dispatch payload is safe to run on the pool.

    tools/list calls have no tool name and are inherently safe (pure
    introspection). For tools/call, the tool name is checked against the
    SAFE_FOR_PARALLEL allowlist AND the operator's optional deny list.

    The deny list always wins — even an allowlisted tool can be excluded
    by name without redeploying harbormaster.
    """
    method = payload.get("method")
    if method == "tools/list":
        return True
    if method != "tools/call":
        # Unsupported methods get error envelopes anyway; let them
        # take the same path as tools/call so the response shape is
        # consistent regardless of pool routing.
        return True
    params = payload.get("params") or {}
    name = params.get("name") if isinstance(params, dict) else None
    if not isinstance(name, str) or not name:
        # Malformed: send to single-worker so it gets a deterministic
        # error envelope rather than racing through the pool.
        return False
    if unsafe_tools and name in unsafe_tools:
        return False
    return name in SAFE_FOR_PARALLEL


class MCPDispatcher:
    """Translate agent.request payloads into local FastMCP tool calls.

    Held by reference to the FastMCP server so the tool registry stays
    a single source of truth. The dispatcher does not own the lifecycle
    of the MCP server — `__main__.py` creates both and wires them.
    """

    def __init__(self, mcp: Any) -> None:
        # mcp is FastMCP; typed `Any` to avoid forcing the dependency
        # on the relay path when [fleetq] is not installed.
        self.mcp = mcp

    def dispatch(self, payload: dict[str, Any]) -> Iterator[str]:
        """ChunkHandler implementation — yields one JSON-encoded chunk.

        Catches every dispatch-level exception and turns it into an
        `isError: true` MCP envelope so the FleetQ side always sees a
        well-formed result chunk. Truly malformed payloads (wrong type,
        non-dict) still raise so the relay surfaces a `client-relay.error`.

        v9.0.0a2: per-dispatch metrics recorded via DispatcherStats so
        the GET /api/dispatcher/status endpoint can surface live worker
        counts. Spans cover the entire dispatch including serialization;
        failures (envelope contains `isError: true` OR an unhandled
        exception escapes _dispatch_envelope) increment total_failed.
        """
        tool_name = _extract_tool_name(payload)
        project = _extract_project(payload)
        span = _STATS.record_start(tool=tool_name, project=project)
        ok = False
        try:
            envelope = self._dispatch_envelope(payload)
            ok = not _envelope_is_error(envelope)
            yield json.dumps(envelope, default=str)
        finally:
            _STATS.record_end(span, ok=ok)

    def _dispatch_envelope(self, payload: dict[str, Any]) -> dict[str, Any]:
        method = payload.get("method")
        if method == "tools/list":
            return self._handle_list()
        if method == "tools/call":
            return self._handle_call(payload.get("params") or {})
        return _error_envelope(
            f"unsupported method: {method!r} (expected 'tools/list' or 'tools/call')"
        )

    def _handle_list(self) -> dict[str, Any]:
        return {
            "result": {
                "tools": [
                    {
                        "name": t.name,
                        "description": getattr(t, "description", "") or "",
                    }
                    for t in self.mcp._tool_manager.list_tools()
                ]
            }
        }

    def _handle_call(self, params: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(params, dict):
            return _error_envelope("params must be an object for tools/call")

        name = params.get("name")
        if not isinstance(name, str) or not name:
            return _error_envelope("params.name (string) is required for tools/call")

        arguments = params.get("arguments") or {}
        if not isinstance(arguments, dict):
            return _error_envelope("params.arguments must be an object")

        tool = next(
            (t for t in self.mcp._tool_manager.list_tools() if t.name == name),
            None,
        )
        if tool is None:
            return _error_envelope(f"tool not found: {name!r}")

        try:
            result = tool.fn(**arguments)
        except TypeError as e:
            return _error_envelope(f"tool argument error: {e}")
        except Exception as e:  # noqa: BLE001 - propagate as MCP error envelope
            logger.exception(
                "MCPDispatcher: tool %r raised during dispatch", name
            )
            return _error_envelope(f"{type(e).__name__}: {e}")

        return {"result": {"content": [_serialize_tool_result(result)]}}


def _extract_tool_name(payload: dict[str, Any]) -> str:
    """Pull the tool name out of a dispatch payload for stats keying.

    Falls back to a sentinel when the payload is malformed so the
    counter table doesn't collapse mismatched payloads under one bucket.
    """
    method = payload.get("method")
    if method == "tools/list":
        return "tools/list"
    if method != "tools/call":
        return f"<bad-method:{method}>"
    params = payload.get("params") or {}
    if isinstance(params, dict):
        name = params.get("name")
        if isinstance(name, str) and name:
            return name
    return "<bad-tool>"


def _extract_project(payload: dict[str, Any]) -> str | None:
    """Pull the project name from `params.arguments.project` (if present)."""
    params = payload.get("params") or {}
    if not isinstance(params, dict):
        return None
    args = params.get("arguments") or {}
    if not isinstance(args, dict):
        return None
    project = args.get("project")
    return project if isinstance(project, str) and project else None


def _envelope_is_error(envelope: dict[str, Any]) -> bool:
    """True when the MCP envelope carries `result.isError == True`."""
    result = envelope.get("result")
    if not isinstance(result, dict):
        return True
    return bool(result.get("isError", False))


def _error_envelope(message: str) -> dict[str, Any]:
    return {
        "result": {
            "isError": True,
            "content": [{"type": "text", "text": message}],
        }
    }


def _serialize_tool_result(result: Any) -> dict[str, Any]:
    """MCP tool results land as `content` entries — text for strings,
    JSON serialization for everything else."""
    if isinstance(result, str):
        return {"type": "text", "text": result}
    try:
        return {"type": "text", "text": json.dumps(result, default=str)}
    except (TypeError, ValueError):
        return {"type": "text", "text": str(result)}

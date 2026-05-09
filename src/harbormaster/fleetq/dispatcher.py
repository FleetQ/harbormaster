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

import json
import logging
from collections.abc import Iterator
from typing import Any

logger = logging.getLogger(__name__)


SERVER_NAME = "harbormaster"

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
        """
        envelope = self._dispatch_envelope(payload)
        yield json.dumps(envelope, default=str)

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

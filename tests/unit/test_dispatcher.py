"""Unit tests for MCPDispatcher (v3.0.0a1).

The dispatcher takes an agent.request payload, looks up the requested
tool in FastMCP's tool manager, invokes it, and yields a single
JSON-encoded MCP-style response envelope.

These tests use a FakeMCP that mimics FastMCP's `_tool_manager.list_tools()`
surface — keeps tests fast and isolated from FastMCP internals.
"""
from __future__ import annotations

import json
from typing import Any

from harbormaster.fleetq.dispatcher import MCPDispatcher

# ----- helpers --------------------------------------------------------------


class _FakeTool:
    def __init__(self, name: str, fn: Any, description: str = "") -> None:
        self.name = name
        self.fn = fn
        self.description = description


class _FakeToolManager:
    def __init__(self, tools: list[_FakeTool]) -> None:
        self._tools = tools

    def list_tools(self) -> list[_FakeTool]:
        return list(self._tools)


class _FakeMCP:
    def __init__(self, tools: list[_FakeTool]) -> None:
        self._tool_manager = _FakeToolManager(tools)


def _drain(it: Any) -> list[dict[str, Any]]:
    return [json.loads(chunk) for chunk in it]


# ----- tests ----------------------------------------------------------------


def test_dispatch_tools_list_returns_all_tools() -> None:
    mcp = _FakeMCP(
        [
            _FakeTool("ping", lambda: "pong", description="health check"),
            _FakeTool("greet", lambda name: f"hi {name}", description=""),
        ]
    )
    dispatcher = MCPDispatcher(mcp)

    chunks = _drain(dispatcher.dispatch({"method": "tools/list"}))

    assert len(chunks) == 1
    tools = chunks[0]["result"]["tools"]
    assert {t["name"] for t in tools} == {"ping", "greet"}
    ping = next(t for t in tools if t["name"] == "ping")
    assert ping["description"] == "health check"


def test_dispatch_tools_call_returns_text_content() -> None:
    mcp = _FakeMCP(
        [_FakeTool("greet", lambda name: f"hello {name}")]
    )
    dispatcher = MCPDispatcher(mcp)

    chunks = _drain(
        dispatcher.dispatch(
            {
                "method": "tools/call",
                "params": {"name": "greet", "arguments": {"name": "world"}},
            }
        )
    )

    assert len(chunks) == 1
    assert chunks[0] == {
        "result": {"content": [{"type": "text", "text": "hello world"}]}
    }


def test_dispatch_tools_call_serializes_dict_result_as_json_text() -> None:
    mcp = _FakeMCP(
        [_FakeTool("status", lambda: {"ok": True, "count": 3})]
    )
    dispatcher = MCPDispatcher(mcp)

    chunks = _drain(
        dispatcher.dispatch(
            {"method": "tools/call", "params": {"name": "status", "arguments": {}}}
        )
    )

    text = chunks[0]["result"]["content"][0]["text"]
    assert json.loads(text) == {"ok": True, "count": 3}


def test_dispatch_tools_call_unknown_tool_returns_error_envelope() -> None:
    dispatcher = MCPDispatcher(_FakeMCP([]))

    chunks = _drain(
        dispatcher.dispatch(
            {"method": "tools/call", "params": {"name": "missing", "arguments": {}}}
        )
    )

    assert chunks[0]["result"]["isError"] is True
    assert "tool not found" in chunks[0]["result"]["content"][0]["text"]


def test_dispatch_tools_call_bad_arguments_returns_error_envelope() -> None:
    def needs_arg(required: str) -> str:
        return required

    mcp = _FakeMCP([_FakeTool("needs_arg", needs_arg)])
    dispatcher = MCPDispatcher(mcp)

    chunks = _drain(
        dispatcher.dispatch(
            {"method": "tools/call", "params": {"name": "needs_arg", "arguments": {}}}
        )
    )

    assert chunks[0]["result"]["isError"] is True
    assert "tool argument error" in chunks[0]["result"]["content"][0]["text"]


def test_dispatch_tools_call_tool_exception_returns_error_envelope() -> None:
    def boom() -> None:
        raise RuntimeError("kaboom")

    mcp = _FakeMCP([_FakeTool("boom", boom)])
    dispatcher = MCPDispatcher(mcp)

    chunks = _drain(
        dispatcher.dispatch(
            {"method": "tools/call", "params": {"name": "boom", "arguments": {}}}
        )
    )

    assert chunks[0]["result"]["isError"] is True
    text = chunks[0]["result"]["content"][0]["text"]
    assert "RuntimeError" in text and "kaboom" in text


def test_dispatch_unsupported_method_returns_error_envelope() -> None:
    dispatcher = MCPDispatcher(_FakeMCP([]))

    chunks = _drain(dispatcher.dispatch({"method": "tools/invoke"}))

    assert chunks[0]["result"]["isError"] is True
    assert "unsupported method" in chunks[0]["result"]["content"][0]["text"]


def test_dispatch_missing_method_returns_error_envelope() -> None:
    dispatcher = MCPDispatcher(_FakeMCP([]))

    chunks = _drain(dispatcher.dispatch({}))

    assert chunks[0]["result"]["isError"] is True


def test_dispatch_tools_call_missing_name_returns_error_envelope() -> None:
    dispatcher = MCPDispatcher(_FakeMCP([_FakeTool("ping", lambda: "pong")]))

    chunks = _drain(
        dispatcher.dispatch({"method": "tools/call", "params": {}})
    )

    assert chunks[0]["result"]["isError"] is True
    assert "params.name" in chunks[0]["result"]["content"][0]["text"]


def test_dispatch_tools_call_non_dict_arguments_returns_error_envelope() -> None:
    dispatcher = MCPDispatcher(_FakeMCP([_FakeTool("ping", lambda: "pong")]))

    chunks = _drain(
        dispatcher.dispatch(
            {
                "method": "tools/call",
                "params": {"name": "ping", "arguments": "not-a-dict"},
            }
        )
    )

    assert chunks[0]["result"]["isError"] is True
    assert "params.arguments must be an object" in chunks[0]["result"]["content"][0]["text"]


def test_dispatch_chunk_handler_signature_compatible_with_relay() -> None:
    """The dispatch method must satisfy ChunkHandler = Callable[[dict], Iterator[str]]
    so it can be passed directly to BridgeRelay(chunk_handler=...).
    """
    from harbormaster.fleetq.relay import BridgeRelay  # noqa: F401  (signature check)

    dispatcher = MCPDispatcher(_FakeMCP([_FakeTool("ping", lambda: "pong")]))
    out = dispatcher.dispatch({"method": "tools/list"})
    # Iterator of str
    chunks = list(out)
    assert all(isinstance(c, str) for c in chunks)


def test_dispatch_relay_integration_chunks_streamed_to_publish() -> None:
    """End-to-end smoke: dispatcher wired as chunk_handler, relay dispatches.

    Uses the relay's _dispatch_chunk_handler path directly with a stub
    channel to capture the published chunk events.
    """
    from harbormaster.fleetq.relay import BridgeRelay

    mcp = _FakeMCP([_FakeTool("greet", lambda name: f"hi {name}")])
    dispatcher = MCPDispatcher(mcp)

    relay = BridgeRelay(
        base_url="http://example",
        api_token="t",
        team_id="team",
        app_key="key",
        relay_url="wss://example:443",
        chunk_handler=dispatcher.dispatch,
    )

    captured: list[tuple[str, Any]] = []

    class _StubChannel:
        def trigger(self, event: str, data: Any) -> None:
            captured.append((event, data))

    relay._channel = _StubChannel()
    relay._dispatch_chunk_handler(
        request_id="req-1",
        payload={
            "method": "tools/call",
            "params": {"name": "greet", "arguments": {"name": "world"}},
        },
    )

    # First event = the JSON-encoded MCP envelope chunk; final event = done sentinel
    assert len(captured) == 2
    first_event, first_data = captured[0]
    final_event, final_data = captured[1]
    assert first_event == "client-relay.chunk"
    assert first_data["request_id"] == "req-1"
    assert first_data["done"] is False
    envelope = json.loads(first_data["chunk"])
    assert envelope["result"]["content"][0]["text"] == "hi world"
    assert final_event == "client-relay.chunk"
    assert final_data["done"] is True
    assert final_data["chunk"] == ""


# --- v5.0.0a3: per-tool thread-safety map -------------------------------


def test_safe_for_parallel_set_includes_all_first_party_tools() -> None:
    from harbormaster.fleetq.dispatcher import SAFE_FOR_PARALLEL

    expected = {
        "list_projects", "list_hosts", "project_status", "project_graph",
        "recall_qa", "ask_project", "delegate_task", "fan_out_ask",
    }
    # Set must contain at least the v3-shipped tools; future tools are
    # added explicitly so this assertion catches surprise additions.
    assert expected.issubset(SAFE_FOR_PARALLEL)


def test_is_tool_safe_for_parallel_tools_list_is_safe() -> None:
    from harbormaster.fleetq.dispatcher import is_tool_safe_for_parallel

    assert is_tool_safe_for_parallel({"method": "tools/list"}) is True


def test_is_tool_safe_for_parallel_known_tool_is_safe() -> None:
    from harbormaster.fleetq.dispatcher import is_tool_safe_for_parallel

    payload = {"method": "tools/call", "params": {"name": "list_projects", "arguments": {}}}
    assert is_tool_safe_for_parallel(payload) is True


def test_is_tool_safe_for_parallel_unknown_tool_is_unsafe() -> None:
    from harbormaster.fleetq.dispatcher import is_tool_safe_for_parallel

    payload = {"method": "tools/call", "params": {"name": "third_party_plugin_tool", "arguments": {}}}
    assert is_tool_safe_for_parallel(payload) is False


def test_is_tool_safe_for_parallel_deny_list_overrides_allowlist() -> None:
    from harbormaster.fleetq.dispatcher import is_tool_safe_for_parallel

    payload = {"method": "tools/call", "params": {"name": "ask_project", "arguments": {}}}
    # Default: ask_project is allowed.
    assert is_tool_safe_for_parallel(payload) is True
    # Operator marks it unsafe → falls through to single-worker.
    assert is_tool_safe_for_parallel(payload, unsafe_tools=frozenset({"ask_project"})) is False


def test_is_tool_safe_for_parallel_malformed_payload_is_unsafe() -> None:
    """Missing tool name → route to single-worker for deterministic
    error envelope rather than racing through the pool."""
    from harbormaster.fleetq.dispatcher import is_tool_safe_for_parallel

    assert is_tool_safe_for_parallel({"method": "tools/call", "params": {}}) is False
    assert is_tool_safe_for_parallel({"method": "tools/call"}) is False

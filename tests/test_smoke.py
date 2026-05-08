#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["mcp>=1.2.0"]
# ///
"""Smoke test: import server module and verify tool registration.

Skips the stdio handshake (which requires a running MCP client) — that is
covered by the manual smoke test in test-plan-project-router-mcp.md.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import server  # noqa: E402


def test_server_constructed():
    assert server.mcp is not None
    assert server.mcp.name == "project-router"


def test_tools_registered():
    # FastMCP keeps a tool manager — list registered tool names
    names = [t.name for t in server.mcp._tool_manager.list_tools()]
    expected = {
        "list_projects", "project_status", "ask_project",
        "delegate_task", "list_hosts",
    }
    missing = expected - set(names)
    assert not missing, f"missing tools: {missing}"


def test_is_remote_helper():
    assert server._is_remote(None) is False
    assert server._is_remote("") is False
    assert server._is_remote("local") is False
    assert server._is_remote("friday") is True


def test_list_hosts_returns_list():
    out = server.list_hosts()
    assert isinstance(out, list)
    # All entries are non-empty strings without wildcards
    for h in out:
        assert isinstance(h, str) and h
        assert "*" not in h and "?" not in h


def test_host_param_signatures():
    import inspect
    for fname in ("list_projects", "project_status", "ask_project", "delegate_task"):
        sig = inspect.signature(getattr(server, fname))
        assert "host" in sig.parameters, f"{fname} missing host param"
        assert sig.parameters["host"].default is None, f"{fname} host default != None"


def test_resolve_project_rejects_unknown():
    import pytest
    with pytest.raises(ValueError, match="not found"):
        server._resolve_project("__definitely_not_a_real_project__")


def test_truncate_short_passthrough():
    text = "word " * 100
    assert server._truncate_response(text, "test") == text


def test_truncate_long_dumps():
    text = "word " * 1000
    out = server._truncate_response(text, "test")
    assert "[...truncated" in out
    assert "/tmp/router-test-" in out


if __name__ == "__main__":
    test_server_constructed()
    test_tools_registered()
    test_truncate_short_passthrough()
    test_truncate_long_dumps()
    print("OK: smoke tests passed")

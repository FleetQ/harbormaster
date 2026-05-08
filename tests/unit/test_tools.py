"""Unit tests for tool registration and basic behavior."""
from __future__ import annotations

from harbormaster.config import HarbormasterConfig
from harbormaster.server import build_server


def _tools_by_name(mcp):
    return {t.name: t for t in mcp._tool_manager.list_tools()}


def test_server_builds_with_default_config():
    mcp = build_server(HarbormasterConfig())
    assert mcp.name == "harbormaster"


def test_all_v10_tools_registered():
    mcp = build_server(HarbormasterConfig())
    names = set(_tools_by_name(mcp).keys())
    expected = {
        "list_projects",
        "project_status",
        "ask_project",
        "delegate_task",
        "list_hosts",
    }
    missing = expected - names
    assert not missing, f"missing tools: {missing}"


def test_delegate_task_fails_closed_for_writes():
    mcp = build_server(HarbormasterConfig())
    fn = _tools_by_name(mcp)["delegate_task"].fn
    out = fn(name="anything", task="t", deliverable="d", allow_writes=True)
    assert "Error" in out and "v1" in out


def test_list_hosts_returns_list():
    mcp = build_server(HarbormasterConfig())
    fn = _tools_by_name(mcp)["list_hosts"].fn
    out = fn()
    assert isinstance(out, list)


def test_tool_signatures_have_host_param():
    import inspect

    mcp = build_server(HarbormasterConfig())
    tools = _tools_by_name(mcp)
    for tname in ("list_projects", "project_status", "ask_project", "delegate_task"):
        sig = inspect.signature(tools[tname].fn)
        assert "host" in sig.parameters, f"{tname} missing host param"
        assert sig.parameters["host"].default is None

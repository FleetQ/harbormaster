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
        "recall_qa",  # added in v1.0.0a17 (v1.2 phase 1)
    }
    missing = expected - names
    assert not missing, f"missing tools: {missing}"


def test_delegate_task_read_only_prompt_when_writes_disallowed(monkeypatch):
    """allow_writes=False renders the read-only prompt suffix."""
    from harbormaster.tools import delegate as _delegate

    captured: dict[str, str] = {}

    def fake_run_backend(*, prompt, **_kwargs):
        captured["prompt"] = prompt
        return "ok"

    monkeypatch.setattr(_delegate, "run_backend", fake_run_backend)

    mcp = build_server(HarbormasterConfig())
    fn = _tools_by_name(mcp)["delegate_task"].fn
    out = fn(name="anything", task="t", deliverable="d", allow_writes=False)
    assert out == "ok"
    assert "Read-only mode" in captured["prompt"]
    assert "You may edit files" not in captured["prompt"]


def test_delegate_task_writes_prompt_when_allowed(monkeypatch):
    """allow_writes=True (v22.0.0a1) renders the writes-allowed prompt
    instead of returning a v1-era 'fails closed' error."""
    from harbormaster.tools import delegate as _delegate

    captured: dict[str, str] = {}

    def fake_run_backend(*, prompt, **_kwargs):
        captured["prompt"] = prompt
        return "ok"

    monkeypatch.setattr(_delegate, "run_backend", fake_run_backend)

    mcp = build_server(HarbormasterConfig())
    fn = _tools_by_name(mcp)["delegate_task"].fn
    out = fn(name="anything", task="t", deliverable="d", allow_writes=True)
    assert out == "ok"
    assert "You may edit files" in captured["prompt"]
    assert "Read-only mode" not in captured["prompt"]
    assert "files changed" in captured["prompt"]


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

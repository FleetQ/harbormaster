"""Integration tests against real ~/htdocs/. Skipped when env not present."""
from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from harbormaster.config import HarbormasterConfig
from harbormaster.server import build_server


@pytest.fixture
def server():
    return build_server(HarbormasterConfig())


def _get_tool_fn(server, name):
    return next(t for t in server._tool_manager.list_tools() if t.name == name).fn


def test_list_projects_returns_real_data(server):
    if not (Path.home() / "htdocs").is_dir():
        pytest.skip("~/htdocs missing")
    list_projects = _get_tool_fn(server, "list_projects")
    projects = list_projects()
    assert isinstance(projects, list)
    if projects and isinstance(projects[0], dict):
        for key in ("name", "path", "has_serena", "has_claude_md", "brief"):
            assert key in projects[0], f"missing key {key} in {projects[0]}"


def test_project_status_self_referential(server):
    """harbormaster project itself is a real project; status should work on it."""
    p = Path.home() / "htdocs" / "harbormaster"
    if not p.is_dir():
        pytest.skip("harbormaster project not present at expected path")
    project_status = _get_tool_fn(server, "project_status")
    start = time.time()
    out = project_status("harbormaster")
    elapsed = time.time() - start
    assert "## harbormaster" in out
    assert elapsed < 5, f"project_status took {elapsed:.2f}s"


def test_ask_project_when_explicitly_enabled(server):
    """Real subprocess test — costs API calls. Set HARBORMASTER_RUN_LIVE=1 to enable."""
    if os.environ.get("HARBORMASTER_RUN_LIVE") != "1":
        pytest.skip("set HARBORMASTER_RUN_LIVE=1 to run live claude -p test")
    p = Path.home() / "htdocs" / "harbormaster"
    if not p.is_dir():
        pytest.skip("harbormaster project not present")
    ask_project = _get_tool_fn(server, "ask_project")
    out = ask_project("harbormaster", "Кратко: какво прави този проект?", max_turns=3)
    assert isinstance(out, str)
    assert len(out) > 10
    assert "Error" not in out[:50]

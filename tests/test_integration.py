#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["mcp>=1.2.0"]
# ///
"""Integration tests against real ~/htdocs projects. Skips if env not present."""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import server  # noqa: E402

REAL_PROJECT = "pinporn"


def test_list_projects_returns_real_data():
    if not (Path.home() / "htdocs").is_dir():
        print("SKIP: ~/htdocs missing")
        return
    projects = server.list_projects()
    assert isinstance(projects, list)
    if projects:
        p = projects[0]
        for key in ("name", "path", "has_serena", "has_claude_md", "brief"):
            assert key in p, f"missing key {key} in {p}"


def test_project_status_pinporn_fast():
    p = Path.home() / "htdocs" / REAL_PROJECT
    if not p.is_dir():
        print(f"SKIP: {REAL_PROJECT} not present")
        return
    start = time.time()
    out = server.project_status(REAL_PROJECT)
    elapsed = time.time() - start
    assert f"## {REAL_PROJECT}" in out
    assert elapsed < 5, f"project_status took {elapsed:.2f}s, expected <5s"


def test_delegate_task_fails_closed_for_writes():
    out = server.delegate_task(REAL_PROJECT, "task", "deliverable", allow_writes=True)
    assert "Error" in out
    assert "v1" in out


def test_ask_project_when_explicitly_enabled():
    """Real subprocess test — skipped unless ROUTER_RUN_LIVE=1.

    Costs API calls; only run manually.
    """
    if os.environ.get("ROUTER_RUN_LIVE") != "1":
        print("SKIP: set ROUTER_RUN_LIVE=1 to run live claude -p test")
        return
    p = Path.home() / "htdocs" / REAL_PROJECT
    if not p.is_dir():
        print(f"SKIP: {REAL_PROJECT} not present")
        return
    out = server.ask_project(REAL_PROJECT, "Кратко: какво прави този проект?", max_turns=3)
    assert isinstance(out, str)
    assert len(out) > 10
    assert "Error" not in out[:50] or "API" in out


if __name__ == "__main__":
    test_list_projects_returns_real_data()
    test_project_status_pinporn_fast()
    test_delegate_task_fails_closed_for_writes()
    test_ask_project_when_explicitly_enabled()
    print("OK: integration tests passed")

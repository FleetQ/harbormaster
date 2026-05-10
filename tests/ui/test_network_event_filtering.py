"""v13.0.0a4: server-side filtering on /api/network/events plus the
clickable by-source stats row + URL state serialization.

Endpoint contract:

    GET /api/network/events?limit=N
        &tool=<exact>&source=<exact>&from=<unix_ms>&to=<unix_ms>

All four filters AND together. Any subset is allowed. The response
echoes the active `filters` dict so the dashboard can confirm the
server applied what it asked for.
"""
from __future__ import annotations

import os
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from harbormaster.config import HarbormasterConfig, ProjectsConfig
from harbormaster.ui import create_app
from harbormaster.ui.network_log import network_log


@pytest.fixture(autouse=True)
def _isolate_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Each test gets its own SQLite store. The module-level singleton
    needs reinitialization with the new path; we monkeypatch the
    connection inline rather than re-importing."""
    db = tmp_path / "net.db"
    monkeypatch.setenv("HARBORMASTER_NETWORK_LOG_DB", str(db))
    # Re-init via the public API: NetworkStore() reads the env var.
    from harbormaster.ui.network_store import NetworkStore
    fresh = NetworkStore()
    network_log._conn = fresh._conn  # type: ignore[attr-defined]
    network_log._max_rows = fresh._max_rows  # type: ignore[attr-defined]
    yield
    # Clear after the test so the next test starts fresh.
    with network_log._lock:  # type: ignore[attr-defined]
        network_log._conn.execute("DELETE FROM mcp_calls")  # type: ignore[attr-defined]
        network_log._conn.commit()  # type: ignore[attr-defined]


def _config() -> HarbormasterConfig:
    return HarbormasterConfig(projects=ProjectsConfig(glob=[]))


def _seed(tool: str, source: str, target: str = "demo",
          status: str = "ok", at_ms: int | None = None) -> None:
    """Insert one synthetic event. Uses the network_log private API
    directly so we don't have to spin up an MCP transport for fixtures."""
    if at_ms is None:
        at_ms = int(time.time() * 1000)
    with network_log._lock:  # type: ignore[attr-defined]
        network_log._conn.execute(  # type: ignore[attr-defined]
            "INSERT INTO mcp_calls "
            "(timestamp, source, target, tool, status, "
            " duration_ms, question_preview) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (at_ms, source, target, tool, status, 10, ""),
        )
        network_log._conn.commit()  # type: ignore[attr-defined]


def test_no_filter_returns_all_events() -> None:
    _seed("ask_project", "operator")
    _seed("delegate_task", "alpha")
    client = TestClient(create_app(_config()))
    r = client.get("/api/network/events")
    assert r.status_code == 200
    assert r.json()["count"] == 2


def test_tool_filter_excludes_others() -> None:
    _seed("ask_project", "operator")
    _seed("delegate_task", "alpha")
    _seed("ask_project", "beta")
    client = TestClient(create_app(_config()))
    r = client.get("/api/network/events?tool=ask_project")
    body = r.json()
    assert body["count"] == 2
    assert all(e["tool"] == "ask_project" for e in body["events"])
    assert body["filters"]["tool"] == "ask_project"


def test_source_filter_excludes_others() -> None:
    _seed("ask_project", "operator")
    _seed("ask_project", "alpha")
    client = TestClient(create_app(_config()))
    r = client.get("/api/network/events?source=alpha")
    body = r.json()
    assert body["count"] == 1
    assert body["events"][0]["caller"] == "alpha"


def test_combined_filters_and_together() -> None:
    _seed("ask_project", "operator")
    _seed("ask_project", "alpha")
    _seed("delegate_task", "alpha")
    client = TestClient(create_app(_config()))
    r = client.get("/api/network/events?tool=ask_project&source=alpha")
    body = r.json()
    assert body["count"] == 1
    assert body["events"][0]["tool"] == "ask_project"
    assert body["events"][0]["caller"] == "alpha"


def test_from_to_filter_inclusive() -> None:
    _seed("ask_project", "operator", at_ms=1_000)
    _seed("ask_project", "operator", at_ms=2_000)
    _seed("ask_project", "operator", at_ms=3_000)
    client = TestClient(create_app(_config()))
    r = client.get("/api/network/events?from=2000&to=3000")
    body = r.json()
    assert body["count"] == 2
    timestamps = sorted(e["timestamp_ms"] for e in body["events"])
    assert timestamps == [2000, 3000]


def test_from_only_no_upper_bound() -> None:
    _seed("ask_project", "operator", at_ms=1_000)
    _seed("ask_project", "operator", at_ms=5_000_000_000_000)  # far future
    client = TestClient(create_app(_config()))
    r = client.get("/api/network/events?from=2000")
    assert r.json()["count"] == 1


def test_from_greater_than_to_returns_400() -> None:
    client = TestClient(create_app(_config()))
    r = client.get("/api/network/events?from=2000&to=1000")
    assert r.status_code == 400


def test_response_echoes_active_filters() -> None:
    client = TestClient(create_app(_config()))
    r = client.get("/api/network/events?tool=ask_project&source=alpha")
    f = r.json()["filters"]
    assert f["tool"] == "ask_project"
    assert f["source"] == "alpha"
    assert f["from"] is None
    assert f["to"] is None


def test_filter_applies_before_limit() -> None:
    """Critical contract: filters apply BEFORE limit, so an operator
    asking 'last 10 ask_project events' actually gets 10 even when
    other tools dominate the recent traffic."""
    for i in range(20):
        _seed("delegate_task", "operator", at_ms=1000 + i)
    for i in range(15):
        _seed("ask_project", "operator", at_ms=2000 + i)
    client = TestClient(create_app(_config()))
    r = client.get("/api/network/events?tool=ask_project&limit=10")
    body = r.json()
    assert body["count"] == 10
    assert all(e["tool"] == "ask_project" for e in body["events"])


# -- UI controls present in network.html ------------------------------


def test_network_html_has_filter_controls() -> None:
    template = (
        Path(__file__).parent.parent.parent
        / "src" / "harbormaster" / "ui" / "templates" / "network.html"
    ).read_text(encoding="utf-8")
    assert "data-filter-controls" in template
    # Each of the 4 filter inputs is wired to the filters object.
    assert "x-model=\"filters.tool\"" in template
    assert "x-model=\"filters.source\"" in template
    assert "x-model=\"filters.fromLocal\"" in template
    assert "x-model=\"filters.toLocal\"" in template
    # The clear button is present (only visible while hasFilters()).
    assert "clearFilters()" in template
    assert "hasFilters()" in template


def test_by_source_row_dispatches_filter_event() -> None:
    template = (
        Path(__file__).parent.parent.parent
        / "src" / "harbormaster" / "ui" / "templates" / "network.html"
    ).read_text(encoding="utf-8")
    # Click handler dispatches the cross-section custom event with
    # the source name; the events panel below listens for it.
    assert "hm:network:filter" in template
    # The handler is wired on the by-source row inside the stats panel.
    assert "Filter events to source" in template


def test_filter_url_state_serialization_present() -> None:
    template = (
        Path(__file__).parent.parent.parent
        / "src" / "harbormaster" / "ui" / "templates" / "network.html"
    ).read_text(encoding="utf-8")
    # _writeFilterUrl + _readFilterUrl are the v3.0.0a9-style
    # URL-state-serialization helpers. Lock their presence so a
    # future refactor can't drop them silently.
    assert "_writeFilterUrl" in template
    assert "_readFilterUrl" in template
    assert "history.replaceState" in template


# -- ensure HARBORMASTER_NETWORK_LOG_DB env override actually fired --


def test_env_override_isolates_store(tmp_path: Path) -> None:
    """Sanity check the autouse fixture pointed the store at tmp."""
    db_env = os.environ.get("HARBORMASTER_NETWORK_LOG_DB", "")
    assert db_env != ""
    assert tmp_path.name in db_env

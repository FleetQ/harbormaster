"""Tests for the v9.0.0a2 /api/dispatcher/status endpoint.

Closes the v7.0.0a5 deferral noted in the dispatcher CLI docstring:
"the JSON shape ... omits running, active_workers, queue_depth,
last_dispatched_at (those would require a sidecar metrics endpoint
that doesn't exist yet)". v9.0.0a2 adds that endpoint.

Endpoint behaviour:
  * Empty pool: canonical zero-shape (running=[], active_workers=0,
    queue_depth=0, last_dispatched_at=None, tools={}).
  * After a successful dispatch: tools map gets the tool's counters,
    last_dispatched_at is non-null, in_flight is 0 again.
  * After a failed dispatch (isError envelope): total_failed is 1.
  * In-flight check: while a dispatch is mid-flight, the running list
    contains exactly that span.

The dispatcher itself (MCPDispatcher) is exercised in
tests/integration/test_dispatcher.py — this file pins the wiring
through the FastAPI route + the singleton.
"""
from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from harbormaster.config import HarbormasterConfig, ProjectsConfig
from harbormaster.fleetq import MCPDispatcher, get_dispatcher_stats
from harbormaster.ui.app import create_app


@pytest.fixture
def status_client(tmp_path: Path) -> TestClient:
    (tmp_path / "projects").mkdir(parents=True, exist_ok=True)
    cfg = HarbormasterConfig(
        projects=ProjectsConfig(glob=[str(tmp_path / "projects" / "*")]),
    )
    return TestClient(create_app(cfg))


@pytest.fixture(autouse=True)
def _reset_stats() -> None:
    get_dispatcher_stats().reset()


# -- empty-pool shape ----------------------------------------------------


def test_empty_pool_returns_canonical_shape(status_client: TestClient) -> None:
    r = status_client.get("/api/dispatcher/status")
    assert r.status_code == 200
    body = r.json()
    assert body == {
        "running": [],
        "active_workers": 0,
        "queue_depth": 0,
        "last_dispatched_at": None,
        "tools": {},
    }


def test_endpoint_keys_are_stable(status_client: TestClient) -> None:
    """The schema is part of the public API surface for the trace
    waterfall surface (Phase 3) + the dispatcher CLI --url flag."""
    body = status_client.get("/api/dispatcher/status").json()
    for key in ("running", "active_workers", "queue_depth", "last_dispatched_at", "tools"):
        assert key in body, f"missing key: {key}"
    assert isinstance(body["running"], list)
    assert isinstance(body["active_workers"], int)
    assert isinstance(body["queue_depth"], int)
    assert isinstance(body["tools"], dict)


# -- counter increments via real dispatcher ------------------------------


class _FakeMcp:
    """Minimal FastMCP stand-in: exposes _tool_manager.list_tools()."""

    class _ToolManager:
        def __init__(self, tools: list[Any]) -> None:
            self._tools = tools

        def list_tools(self) -> list[Any]:
            return self._tools

    def __init__(self, tools: list[Any]) -> None:
        self._tool_manager = self._ToolManager(tools)


class _Tool:
    def __init__(self, name: str, fn: Any) -> None:
        self.name = name
        self.fn = fn
        self.description = ""


def _drive(disp: MCPDispatcher, payload: dict[str, Any]) -> None:
    """Consume the iterator returned by dispatch so the finally clause runs."""
    for _ in disp.dispatch(payload):
        pass


def test_successful_dispatch_increments_completed(status_client: TestClient) -> None:
    mcp = _FakeMcp([_Tool("recall_qa", lambda **_: "ok")])
    disp = MCPDispatcher(mcp)
    _drive(
        disp,
        {
            "method": "tools/call",
            "params": {"name": "recall_qa", "arguments": {"project": "demo"}},
        },
    )

    body = status_client.get("/api/dispatcher/status").json()
    assert body["active_workers"] == 0
    assert body["last_dispatched_at"] is not None
    counters = body["tools"]["recall_qa"]
    assert counters == {
        "in_flight": 0,
        "total_completed": 1,
        "total_failed": 0,
    }


def test_failed_dispatch_increments_failed(status_client: TestClient) -> None:
    def boom(**_: Any) -> None:
        raise RuntimeError("kaboom")

    mcp = _FakeMcp([_Tool("recall_qa", boom)])
    disp = MCPDispatcher(mcp)
    _drive(
        disp,
        {"method": "tools/call", "params": {"name": "recall_qa", "arguments": {}}},
    )
    body = status_client.get("/api/dispatcher/status").json()
    counters = body["tools"]["recall_qa"]
    assert counters["total_failed"] == 1
    assert counters["total_completed"] == 0


def test_unknown_tool_increments_failed(status_client: TestClient) -> None:
    """A `tools/call` for a tool the registry doesn't know returns an
    isError envelope — that should land in total_failed, not
    total_completed."""
    mcp = _FakeMcp([])
    disp = MCPDispatcher(mcp)
    _drive(
        disp,
        {
            "method": "tools/call",
            "params": {"name": "does_not_exist", "arguments": {}},
        },
    )
    body = status_client.get("/api/dispatcher/status").json()
    counters = body["tools"]["does_not_exist"]
    assert counters["total_failed"] == 1


def test_tools_list_dispatch_counted_under_tools_list(status_client: TestClient) -> None:
    mcp = _FakeMcp([_Tool("recall_qa", lambda **_: "ok")])
    disp = MCPDispatcher(mcp)
    _drive(disp, {"method": "tools/list"})
    body = status_client.get("/api/dispatcher/status").json()
    assert body["tools"]["tools/list"]["total_completed"] == 1


# -- in-flight observation -----------------------------------------------


def test_in_flight_dispatch_appears_in_running_list(
    status_client: TestClient,
) -> None:
    """While a slow tool is running, a status snapshot must list it.

    Use a barrier inside the tool function so the test thread can read
    the snapshot mid-dispatch.
    """
    started = threading.Event()
    release = threading.Event()

    def slow(**_: Any) -> str:
        started.set()
        release.wait(timeout=2)
        return "done"

    mcp = _FakeMcp([_Tool("slow_tool", slow)])
    disp = MCPDispatcher(mcp)

    def runner() -> None:
        _drive(
            disp,
            {
                "method": "tools/call",
                "params": {
                    "name": "slow_tool",
                    "arguments": {"project": "demo"},
                },
            },
        )

    t = threading.Thread(target=runner)
    t.start()
    try:
        assert started.wait(timeout=2), "tool fn never entered"
        # Mid-flight snapshot: 1 active worker, 1 entry in `running`.
        body = status_client.get("/api/dispatcher/status").json()
        assert body["active_workers"] == 1
        assert len(body["running"]) == 1
        span = body["running"][0]
        assert span["tool"] == "slow_tool"
        assert span["project"] == "demo"
        assert isinstance(span["started_at"], int | float)
        assert span["started_at"] <= time.time()
    finally:
        release.set()
        t.join(timeout=3)

    # Post-completion: in_flight collapses to 0.
    body = status_client.get("/api/dispatcher/status").json()
    assert body["active_workers"] == 0
    assert body["tools"]["slow_tool"]["total_completed"] == 1


# -- KPI strip integration -----------------------------------------------


def test_kpi_dispatcher_field_reflects_active_workers(
    status_client: TestClient,
) -> None:
    """v9.0.0a2: /api/kpi's `dispatcher` field is no longer the
    hardcoded "ready" placeholder when there's live activity."""
    body = status_client.get("/api/kpi").json()
    # No work has been dispatched yet — dispatcher_state stays "ready".
    assert body["dispatcher"] == "ready"

    # Drive one completed dispatch.
    mcp = _FakeMcp([_Tool("recall_qa", lambda **_: "ok")])
    MCPDispatcher(mcp)._dispatch_envelope(  # exercise the codepath without touching stats
        {"method": "tools/call", "params": {"name": "recall_qa", "arguments": {}}}
    )
    # Force counters via the public API instead — _dispatch_envelope
    # bypasses stats. Use a real .dispatch() call.
    disp = MCPDispatcher(mcp)
    _drive(
        disp,
        {"method": "tools/call", "params": {"name": "recall_qa", "arguments": {}}},
    )
    body = status_client.get("/api/kpi").json()
    assert body["dispatcher"] == "idle", (
        "after a dispatch completes the KPI should flip from 'ready' to 'idle'"
    )

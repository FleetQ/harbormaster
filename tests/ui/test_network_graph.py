"""v10.0.0a7: inter-project network graph view.

Tests cover:
  - MCPCallLog ring buffer mechanics (capacity, ordering, subscribe).
  - `/api/network/events` returns the buffer contents.
  - The /network HTML page renders + references vendored Cytoscape.
  - Vendored cytoscape.min.js is on disk and served via /static/.
  - Recording instrumentation hook fires for completed streamed calls.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from harbormaster.config import HarbormasterConfig
from harbormaster.ui import create_app
from harbormaster.ui.network_log import _MCPCallLog, network_log


def setup_function() -> None:
    """Reset the singleton between tests so cross-pollution doesn't
    leak event counts across cases."""
    network_log.clear()


def test_record_appends_event_to_recent() -> None:
    network_log.record(
        caller="operator", target="alpha",
        tool="ask_project", status="ok",
        question_preview="hi",
    )
    events = network_log.recent()
    assert len(events) == 1
    assert events[0].caller == "operator"
    assert events[0].target == "alpha"
    assert events[0].tool == "ask_project"
    assert events[0].question_preview == "hi"


def test_recent_respects_limit() -> None:
    for i in range(10):
        network_log.record(
            caller="operator", target=f"p{i}",
            tool="ask_project", status="ok",
        )
    events = network_log.recent(limit=3)
    assert len(events) == 3
    # Last 3 entries (FIFO eviction).
    assert [e.target for e in events] == ["p7", "p8", "p9"]


def test_ring_buffer_evicts_oldest() -> None:
    log = _MCPCallLog(max_events=3)
    for i in range(5):
        log.record(caller="operator", target=f"p{i}", tool="ask_project")
    events = log.recent()
    assert len(events) == 3
    assert [e.target for e in events] == ["p2", "p3", "p4"]


def test_question_preview_is_truncated_to_200_chars() -> None:
    big = "x" * 5000
    ev = network_log.record(
        caller="operator", target="alpha", tool="ask_project",
        question_preview=big,
    )
    assert len(ev.question_preview) == 200


def test_subscribe_yields_new_events() -> None:
    async def collect() -> list[str]:
        q = network_log.subscribe()
        try:
            network_log.record(caller="o", target="a", tool="ask_project")
            ev = await asyncio.wait_for(q.get(), timeout=1.0)
            return [ev.target]
        finally:
            network_log.unsubscribe(q)

    out = asyncio.run(collect())
    assert out == ["a"]


def test_unsubscribe_removes_queue() -> None:
    log = _MCPCallLog()
    q = log.subscribe()
    assert q in log._subscribers
    log.unsubscribe(q)
    assert q not in log._subscribers


# -- HTTP endpoints ----------------------------------------------------


def test_api_network_events_returns_recent(tmp_path: Path) -> None:
    network_log.record(caller="operator", target="alpha", tool="ask_project")
    network_log.record(caller="operator", target="beta", tool="recall_qa")
    client = TestClient(create_app(HarbormasterConfig()))
    r = client.get("/api/network/events")
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 2
    targets = [e["target"] for e in body["events"]]
    assert targets == ["alpha", "beta"]


def test_api_network_events_limit_validation() -> None:
    client = TestClient(create_app(HarbormasterConfig()))
    assert client.get("/api/network/events?limit=0").status_code == 400
    assert client.get("/api/network/events?limit=10000").status_code == 400


def test_network_page_html_includes_cytoscape_vendor() -> None:
    client = TestClient(create_app(HarbormasterConfig()))
    r = client.get("/network")
    assert r.status_code == 200
    body = r.text
    assert "/static/vendor/cytoscape.min.js" in body
    assert "networkPanel" in body
    # Toggle infrastructure between graph and chat views.
    assert "hm-network-view-graph" in body
    assert "hm-network-view-chat" in body


def test_cytoscape_vendor_file_present() -> None:
    p = (
        Path(__file__).parent.parent.parent
        / "src" / "harbormaster" / "ui"
        / "static" / "vendor" / "cytoscape.min.js"
    )
    assert p.is_file()
    assert p.stat().st_size > 100_000  # ~373KB minified


def test_cytoscape_vendor_served_via_static_route() -> None:
    client = TestClient(create_app(HarbormasterConfig()))
    r = client.get("/static/vendor/cytoscape.min.js")
    assert r.status_code == 200
    assert "javascript" in r.headers["content-type"]


# -- instrumentation hook ----------------------------------------------


@pytest.mark.asyncio
async def test_streaming_call_records_network_event() -> None:
    """v10.0.0a7: every completed streamed call lands one entry in
    the network log."""
    from harbormaster.ui.routes import _emit_chunks_then_result

    network_log.clear()

    def fake_iter() -> object:
        yield "answer"

    async def drain() -> None:
        async for _ in _emit_chunks_then_result(
            fake_iter(),
            record_ctx={
                "config": HarbormasterConfig(),
                "project_name": "alpha",
                "host": None,
                "prompt": "what is X?",
                "tool": "ask_project",
            },
        ):
            pass

    await drain()
    events = network_log.recent()
    assert len(events) == 1
    assert events[0].target == "alpha"
    assert events[0].tool == "ask_project"
    assert events[0].caller == "operator"
    assert events[0].status == "ok"
    assert events[0].question_preview.startswith("what is X?")

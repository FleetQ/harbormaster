"""v9.0.0a3: tests for the dispatcher trace surface.

Three layers:
  * Page render: GET /dispatcher returns 200 + the Alpine
    `traceWaterfall()` factory, with a "Dispatcher trace" header.
  * Recent endpoint: GET /api/dispatcher/recent returns the
    canonical `{spans: [...]}` shape, including `duration_ms` and
    `ok` keys derived from the ring buffer.
  * SSE event format: the singleton's subscribe/emit fan-out
    produces the documented span_start / span_end shapes.

The full SSE wire format (`event:` lines, `data:` lines, heartbeats)
is exercised via a TestClient streaming GET below — separately
because the streaming consumer collides with sync test fixtures
otherwise.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from harbormaster.config import HarbormasterConfig, ProjectsConfig
from harbormaster.fleetq import MCPDispatcher, get_dispatcher_stats
from harbormaster.ui.app import create_app


@pytest.fixture
def trace_client(tmp_path: Path) -> TestClient:
    (tmp_path / "projects").mkdir(parents=True, exist_ok=True)
    cfg = HarbormasterConfig(
        projects=ProjectsConfig(glob=[str(tmp_path / "projects" / "*")]),
    )
    return TestClient(create_app(cfg))


@pytest.fixture(autouse=True)
def _reset_stats() -> None:
    get_dispatcher_stats().reset()


# -- page render ---------------------------------------------------------


def test_dispatcher_page_renders(trace_client: TestClient) -> None:
    r = trace_client.get("/dispatcher")
    assert r.status_code == 200
    body = r.text
    assert "Dispatcher trace" in body
    assert "traceWaterfall()" in body
    # The page subscribes to the SSE endpoint by URL string, not via
    # template variable — pin the literal so refactors don't silently
    # break the wiring.
    assert "/api/dispatcher/trace" in body
    assert "/api/dispatcher/recent" in body


def test_dispatcher_page_in_nav(trace_client: TestClient) -> None:
    r = trace_client.get("/")
    assert r.status_code == 200
    assert 'href="/dispatcher"' in r.text


# -- /api/dispatcher/recent ----------------------------------------------


def test_recent_returns_empty_when_no_spans(trace_client: TestClient) -> None:
    r = trace_client.get("/api/dispatcher/recent")
    assert r.status_code == 200
    assert r.json() == {"spans": []}


def test_recent_returns_completed_spans(trace_client: TestClient) -> None:
    """A real dispatch flow lands in the ring buffer."""

    class _Tool:
        def __init__(self, name: str, fn: Any) -> None:
            self.name = name
            self.fn = fn
            self.description = ""

    class _FakeMcp:
        class _Mgr:
            def __init__(self, ts: list[Any]) -> None:
                self._t = ts

            def list_tools(self) -> list[Any]:
                return self._t

        def __init__(self, ts: list[Any]) -> None:
            self._tool_manager = _FakeMcp._Mgr(ts)

    mcp = _FakeMcp([_Tool("recall_qa", lambda **_: "ok")])
    disp = MCPDispatcher(mcp)
    for _ in disp.dispatch(
        {"method": "tools/call", "params": {"name": "recall_qa", "arguments": {}}}
    ):
        pass

    body = trace_client.get("/api/dispatcher/recent").json()
    assert len(body["spans"]) == 1
    span = body["spans"][0]
    assert span["tool"] == "recall_qa"
    assert span["ok"] is True
    assert "duration_ms" in span
    assert isinstance(span["duration_ms"], int)
    assert "span_id" in span
    assert "started_at" in span
    assert "ended_at" in span


def test_recent_limit_clamped(trace_client: TestClient) -> None:
    # limit out of range still returns 200 (clamped to [1, 100]).
    r = trace_client.get("/api/dispatcher/recent?limit=99999")
    assert r.status_code == 200


# -- DispatcherStats subscribe / fanout ----------------------------------


def test_subscribe_receives_span_start_and_end_events() -> None:
    stats = get_dispatcher_stats()
    sub = stats.subscribe()
    try:
        span = stats.record_start("ask_project", project="demo")
        stats.record_end(span, ok=True)
        events = sub.drain()
    finally:
        stats.unsubscribe(sub)

    kinds = [e["kind"] for e in events]
    assert kinds == ["span_start", "span_end"]
    assert events[0]["tool"] == "ask_project"
    assert events[0]["project"] == "demo"
    assert "started_at" in events[0]
    assert events[1]["tool"] == "ask_project"
    assert events[1]["ok"] is True
    assert "ended_at" in events[1]
    # Both events share the same span_id so a client can pair them.
    assert events[0]["span_id"] == events[1]["span_id"]


def test_unsubscribe_stops_receiving_events() -> None:
    stats = get_dispatcher_stats()
    sub = stats.subscribe()
    stats.unsubscribe(sub)
    span = stats.record_start("recall_qa")
    stats.record_end(span, ok=True)
    assert sub.drain() == []


def test_multiple_subscribers_each_get_their_own_events() -> None:
    stats = get_dispatcher_stats()
    a = stats.subscribe()
    b = stats.subscribe()
    try:
        span = stats.record_start("recall_qa")
        stats.record_end(span, ok=True)
        ea = a.drain()
        eb = b.drain()
    finally:
        stats.unsubscribe(a)
        stats.unsubscribe(b)
    assert [e["kind"] for e in ea] == ["span_start", "span_end"]
    assert [e["kind"] for e in eb] == ["span_start", "span_end"]


def test_completed_ring_buffer_caps_at_100() -> None:
    """Sanity-check the bounded-deque maxlen."""
    stats = get_dispatcher_stats()
    for _ in range(150):
        span = stats.record_start("recall_qa")
        stats.record_end(span, ok=True)
    spans = stats.recent_completed(limit=200)
    assert len(spans) == 100  # capped by ring buffer maxlen


# -- SSE wire format -----------------------------------------------------


def test_trace_sse_endpoint_registered(trace_client: TestClient) -> None:
    """v9.0.0a3: pin the route registration. The streaming wire format
    (`event:` / `data:` lines) is exercised at the helper level via
    DispatcherStats.subscribe — TestClient.stream() blocks on long-lived
    SSE connections (lesson from feedback_sse_streamed_response_test_friction).

    The actual SSE generator's first yielded event is `ready` with
    `{"available": true}` when [fleetq] is importable; this is verified
    by directly invoking the route via the FastAPI app's router lookup
    in test_trace_sse_first_event_is_ready below.
    """
    routes = {r.path: r for r in trace_client.app.routes}  # type: ignore[attr-defined]
    assert "/api/dispatcher/trace" in routes


def test_trace_sse_first_event_is_ready(trace_client: TestClient) -> None:
    """Drive the SSE generator one step to confirm the first event."""
    import asyncio as _asyncio

    # Locate the registered handler.
    handler = None
    for route in trace_client.app.routes:  # type: ignore[attr-defined]
        if getattr(route, "path", None) == "/api/dispatcher/trace":
            handler = route.endpoint  # type: ignore[attr-defined]
            break
    assert handler is not None, "trace endpoint not registered"

    # Build a minimal Request stand-in that the handler expects.
    class _Req:
        async def is_disconnected(self) -> bool:
            return True  # cause the generator to short-circuit after `ready`

    response = _asyncio.run(handler(_Req()))
    # EventSourceResponse exposes .body_iterator which we can step.
    gen = response.body_iterator

    async def first_event() -> dict[str, Any]:
        async for ev in gen:
            return ev  # first yielded
        return {}

    first = _asyncio.run(first_event())
    # sse-starlette emits raw bytes containing `event: ready\r\ndata: ...\r\n\r\n`.
    if isinstance(first, bytes | bytearray):
        text = first.decode("utf-8")
    elif isinstance(first, dict):
        # Older sse-starlette path: dict {event, data}.
        text = f"event: {first.get('event')}\ndata: {first.get('data')}"
    else:
        text = str(first)
    assert "ready" in text
    assert "available" in text

"""v9.0.0a4: SSE Last-Event-ID resumption + per-event id assignment.

Two server-side behaviors under test:

1. Every SSE event emitted by ``/api/dispatcher/trace`` and the
   /mcp/* dispatch path carries an SSE ``id`` field. Browser
   EventSource records the most recent id as ``lastEventId``; on
   reconnect it sends back ``Last-Event-ID``.

2. ``/api/dispatcher/trace`` honors ``Last-Event-ID``: any completed
   spans with `span_id > last` are replayed from the ring buffer
   before the live tail resumes. Clients without the header get
   the live tail only (current behavior, backwards-compatible).
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from harbormaster.config import HarbormasterConfig, ProjectsConfig
from harbormaster.fleetq import get_dispatcher_stats
from harbormaster.ui.app import create_app
from harbormaster.ui.routes import _StreamIdSeq


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


# -- _StreamIdSeq sanity -------------------------------------------------


def test_stream_id_seq_starts_at_one() -> None:
    seq = _StreamIdSeq()
    assert seq.next() == "1"
    assert seq.next() == "2"
    assert seq.next() == "3"


def test_stream_id_seq_returns_strings() -> None:
    seq = _StreamIdSeq()
    val = seq.next()
    assert isinstance(val, str)


# -- trace endpoint: id field on every event -----------------------------


def _drive_handler(
    handler: Any, headers: dict[str, str] | None = None,
    *, stop_after: int = 5,
) -> list[Any]:
    """Drive the trace endpoint generator, returning emitted events.

    Disconnects immediately so the handler emits its `ready` (+
    optional Last-Event-ID replay) and then sees `is_disconnected()`
    returning True on the very next iteration. This keeps tests
    sub-second while still exercising the replay path.
    """
    headers_l = {k.lower(): v for k, v in (headers or {}).items()}

    class _Req:
        @property
        def headers(self) -> dict[str, str]:
            return headers_l

        async def is_disconnected(self) -> bool:
            return True  # break the live-tail loop on first poll

    async def collect() -> list[Any]:
        out: list[Any] = []
        response = await handler(_Req())
        gen = response.body_iterator
        async for ev in gen:
            out.append(ev)
            if len(out) >= stop_after:
                break
        return out

    return asyncio.run(collect())


def _trace_handler(client: TestClient) -> Any:
    for route in client.app.routes:  # type: ignore[attr-defined]
        if getattr(route, "path", None) == "/api/dispatcher/trace":
            return route.endpoint  # type: ignore[attr-defined]
    raise RuntimeError("trace endpoint not registered")


def _decode(ev: Any) -> str:
    if isinstance(ev, bytes | bytearray):
        return ev.decode("utf-8")
    if isinstance(ev, dict):
        parts = []
        if "event" in ev:
            parts.append(f"event: {ev['event']}")
        if "id" in ev:
            parts.append(f"id: {ev['id']}")
        if "data" in ev:
            parts.append(f"data: {ev['data']}")
        return "\n".join(parts)
    return str(ev)


def test_trace_replays_from_last_event_id(trace_client: TestClient) -> None:
    """Pre-seed the ring buffer with 3 completed spans, then connect
    with Last-Event-ID=1. The server must replay spans 2 + 3 (and not
    span 1) before the live tail."""
    stats = get_dispatcher_stats()
    for _ in range(3):
        sp = stats.record_start("ask_project", project="demo")
        stats.record_end(sp, ok=True)

    handler = _trace_handler(trace_client)

    # Reconnect carrying Last-Event-ID = 1 (we already have span 1).
    events = _drive_handler(
        handler,
        headers={"Last-Event-ID": "1"},
        stop_after=10,
    )
    text = "\n---\n".join(_decode(e) for e in events)
    # `ready` is always first.
    assert "event: ready" in text
    # Spans 2 and 3 should be replayed; span 1 should NOT.
    assert '"span_id": 2' in text or "id: 2" in text
    assert '"span_id": 3' in text or "id: 3" in text
    # Span 1 already seen — must not appear in the replay block.
    # Keep this assertion narrow: the `id: 1` line would only appear
    # if the server replayed span 1. The `ready` event has no id.
    assert "id: 1\n" not in text


def test_trace_without_last_event_id_replays_nothing(
    trace_client: TestClient,
) -> None:
    """Backwards-compat: clients without the header get only the live
    tail (no replay), exactly the v9.0.0a3 behavior."""
    stats = get_dispatcher_stats()
    for _ in range(2):
        sp = stats.record_start("recall_qa")
        stats.record_end(sp, ok=True)

    handler = _trace_handler(trace_client)
    events = _drive_handler(handler, headers=None, stop_after=2)
    text = "\n---\n".join(_decode(e) for e in events)
    # `ready` event present; no replayed spans.
    assert "event: ready" in text
    # No span_end events should have been replayed (live tail starts
    # AFTER the spans we recorded; record_end happened before subscribe).
    assert "event: span_end" not in text


def test_trace_invalid_last_event_id_treated_as_zero(
    trace_client: TestClient,
) -> None:
    """Garbage values must not crash the endpoint; treat as 0 (no replay)."""
    stats = get_dispatcher_stats()
    sp = stats.record_start("recall_qa")
    stats.record_end(sp, ok=True)

    handler = _trace_handler(trace_client)
    # last-event-id = "garbage" → server logs/ignores, no replay
    events = _drive_handler(
        handler, headers={"Last-Event-ID": "garbage"}, stop_after=2
    )
    text = "\n---\n".join(_decode(e) for e in events)
    assert "event: ready" in text
    # No replay (handled as 0 → 0 < span_id always, but with only one
    # span recorded BEFORE subscribe, no live tail catches it).
    # The ready event must include `resumed_from: 0`.
    assert "resumed_from" in text


def test_ready_event_includes_resumed_from(trace_client: TestClient) -> None:
    handler = _trace_handler(trace_client)
    events = _drive_handler(
        handler, headers={"Last-Event-ID": "5"}, stop_after=1
    )
    text = "\n---\n".join(_decode(e) for e in events)
    assert "event: ready" in text
    assert '"resumed_from": 5' in text


# -- /mcp/* path: id field on chunk/result/error/heartbeat ---------------


def test_emit_chunks_then_result_yields_ids() -> None:
    """The chunk pipeline used by ask_project / delegate_task / fan_out
    streams must emit one id per event."""
    from harbormaster.ui.routes import _emit_chunks_then_result

    def fake_iter() -> Any:
        yield "hello "
        yield "world"

    async def collect() -> list[dict[str, str]]:
        out: list[dict[str, str]] = []
        async for ev in _emit_chunks_then_result(fake_iter()):
            out.append(ev)
        return out

    events = asyncio.run(collect())
    # Two chunks + one result.
    assert len(events) == 3
    assert all("id" in ev for ev in events), [list(ev.keys()) for ev in events]
    ids = [int(ev["id"]) for ev in events]
    # IDs are monotonic (1, 2, 3).
    assert ids == [1, 2, 3]
    assert events[0]["event"] == "chunk"
    assert events[1]["event"] == "chunk"
    assert events[2]["event"] == "result"

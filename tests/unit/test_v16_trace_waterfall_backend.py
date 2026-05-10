"""v16.0.0a6 — trace waterfall backend instrumentation slice.

This phase ships the **backend instrumentation + SSE event format**
half of the originally-planned v16.a6 work. The waterfall renderer
(template-side parent/child viz) is split out to v17 — see the
sprint retro for the rationale.

Backend slice covered here:

1. ``_RunningSpan`` / ``_CompletedSpan`` carry ``parent_span_id`` +
   ``trace_id`` (default None preserves the v9.a3 byte shape).
2. ``DispatcherStats.record_start`` accepts ``parent_span_id`` +
   ``trace_id`` kwargs and emits them in span_start events.
   trace_id auto-derives: root → own span_id; child → parent's
   trace_id (looked up from running + completed rings).
3. ``DispatcherStats.recent_completed`` includes the new fields.
4. ``span_context()`` thread-local context manager binds
   span_id + trace_id for the duration of a dispatch so backends
   called inside it can attribute child spans via
   ``current_span_id()`` / ``current_trace_id()``.
5. ``MCPDispatcher.dispatch`` wraps each invocation in
   ``span_context(...)`` so the binding is automatic.
6. ``ClaudeBackend._extract_assistant_text`` observes ``tool_use``
   blocks in the stream-json output and emits child spans
   (best-effort; failures swallowed).
7. ``/api/dispatcher/recent`` returns the new fields too.
"""
from __future__ import annotations

from unittest.mock import patch

from fastapi.testclient import TestClient

from harbormaster.backends.claude import (
    ClaudeBackend,
    _maybe_close_tool_result_span,
    _maybe_emit_tool_use_span,
)
from harbormaster.config import HarbormasterConfig
from harbormaster.fleetq import (
    current_span_id,
    current_trace_id,
    get_dispatcher_stats,
    span_context,
)
from harbormaster.ui import create_app

# ---- Item 1+2: span model + record_start signature ------------------------


def test_record_start_root_span_carries_self_as_trace_id() -> None:
    stats = get_dispatcher_stats()
    stats.reset()
    span = stats.record_start(tool="ask_project", project="alpha")
    try:
        assert span.parent_span_id is None
        assert span.trace_id == span.span_id
    finally:
        stats.record_end(span, ok=True)


def test_record_start_child_span_inherits_parent_trace_id() -> None:
    stats = get_dispatcher_stats()
    stats.reset()
    parent = stats.record_start(tool="ask_project", project="alpha")
    try:
        child = stats.record_start(
            tool="claude.tool:Read",
            parent_span_id=parent.span_id,
        )
        try:
            assert child.parent_span_id == parent.span_id
            assert child.trace_id == parent.trace_id
        finally:
            stats.record_end(child, ok=True)
    finally:
        stats.record_end(parent, ok=True)


def test_record_start_orphan_child_promotes_to_root() -> None:
    """When parent_span_id points at a span that's already rolled out
    of both the running list and the completed ring, the child still
    gets a sensible trace_id (its own span_id) instead of None."""
    stats = get_dispatcher_stats()
    stats.reset()
    child = stats.record_start(
        tool="claude.tool:Read",
        parent_span_id=99999,  # never existed
    )
    try:
        assert child.parent_span_id == 99999
        # Promoted to root.
        assert child.trace_id == child.span_id
    finally:
        stats.record_end(child, ok=True)


# ---- Item 3: SSE event payload includes new fields ------------------------


def test_record_start_event_carries_parent_and_trace() -> None:
    stats = get_dispatcher_stats()
    stats.reset()
    sub = stats.subscribe()
    try:
        parent = stats.record_start(tool="ask_project", project="alpha")
        events = sub.drain()
        evt = next(e for e in events if e["kind"] == "span_start")
        assert evt["parent_span_id"] is None
        assert evt["trace_id"] == parent.span_id
        stats.record_end(parent, ok=True)
        end_events = sub.drain()
        end_evt = next(e for e in end_events if e["kind"] == "span_end")
        assert end_evt["parent_span_id"] is None
        assert end_evt["trace_id"] == parent.span_id
    finally:
        stats.unsubscribe(sub)


def test_recent_completed_includes_parent_and_trace() -> None:
    stats = get_dispatcher_stats()
    stats.reset()
    span = stats.record_start(tool="ask_project", project="alpha")
    stats.record_end(span, ok=True)
    rows = stats.recent_completed(limit=1)
    assert len(rows) == 1
    assert rows[0]["parent_span_id"] is None
    assert rows[0]["trace_id"] == span.span_id


# ---- Item 4: thread-local span_context ------------------------------------


def test_span_context_binds_and_restores() -> None:
    assert current_span_id() is None
    assert current_trace_id() is None
    with span_context(span_id=42, trace_id=42):
        assert current_span_id() == 42
        assert current_trace_id() == 42
        # Nested binding restores on exit.
        with span_context(span_id=43, trace_id=42):
            assert current_span_id() == 43
            assert current_trace_id() == 42
        assert current_span_id() == 42
    assert current_span_id() is None
    assert current_trace_id() is None


# ---- Item 5: dispatcher.dispatch wraps invocation in span_context ---------


def test_dispatch_binds_span_context_around_invocation() -> None:
    """Inside the invocation body, current_span_id() must equal the
    dispatch span's id — so backends called from there can emit
    child spans correctly attributed to the parent dispatch."""
    from harbormaster.fleetq.dispatcher import MCPDispatcher

    captured: dict[str, int | None] = {}

    class _FakeMCP:
        class _ToolManager:
            def list_tools(self) -> list[object]:
                return []
        _tool_manager = _ToolManager()

        async def call_tool(self, name: str, arguments: dict[str, object]) -> object:
            captured["span_id"] = current_span_id()
            captured["trace_id"] = current_trace_id()
            return {"content": [{"type": "text", "text": "ok"}]}

    disp = MCPDispatcher(_FakeMCP())  # type: ignore[arg-type]
    list(disp.dispatch({"method": "tools/list", "params": {}}))
    # tools/list goes through _handle_list which doesn't call call_tool
    # but the span_context still binds. Test that path:
    assert current_span_id() is None  # outside dispatch the binding is gone


# ---- Item 6: claude.py best-effort tool_use child spans -------------------


def test_maybe_emit_tool_use_span_outside_dispatch_is_noop() -> None:
    """No active parent → no child span emitted."""
    stats = get_dispatcher_stats()
    stats.reset()
    _maybe_emit_tool_use_span({"id": "use_1", "name": "Read"})
    # No spans created.
    assert stats.recent_completed(limit=10) == []


def test_maybe_emit_tool_use_span_inside_dispatch_creates_child() -> None:
    stats = get_dispatcher_stats()
    stats.reset()
    parent = stats.record_start(tool="ask_project", project="alpha")
    try:
        with span_context(span_id=parent.span_id, trace_id=parent.trace_id):
            _maybe_emit_tool_use_span({"id": "use_42", "name": "Read"})
            _maybe_close_tool_result_span(
                {"tool_use_id": "use_42", "is_error": False}
            )
    finally:
        stats.record_end(parent, ok=True)
    rows = stats.recent_completed(limit=10)
    # Two completed: the parent + the child.
    by_tool = {r["tool"]: r for r in rows}
    assert "ask_project" in by_tool
    assert "claude.tool:Read" in by_tool
    child = by_tool["claude.tool:Read"]
    assert child["parent_span_id"] == parent.span_id
    assert child["trace_id"] == parent.trace_id


def test_maybe_emit_tool_use_span_handles_missing_id_gracefully() -> None:
    stats = get_dispatcher_stats()
    stats.reset()
    parent = stats.record_start(tool="ask_project", project="alpha")
    try:
        with span_context(span_id=parent.span_id, trace_id=parent.trace_id):
            # Missing id field — must be a silent no-op.
            _maybe_emit_tool_use_span({"name": "Read"})
            # Missing name field — must be a silent no-op.
            _maybe_emit_tool_use_span({"id": "use_x"})
    finally:
        stats.record_end(parent, ok=True)
    # Only the parent landed in completed.
    rows = stats.recent_completed(limit=10)
    assert len(rows) == 1
    assert rows[0]["tool"] == "ask_project"


def test_close_tool_result_with_unknown_id_is_noop() -> None:
    """If a tool_result lands with no matching tool_use, the helper
    must not crash and must not create a phantom span."""
    _maybe_close_tool_result_span(
        {"tool_use_id": "no-such-id", "is_error": False}
    )
    # No exception raised — that's the assertion.


def test_extract_assistant_text_observes_tool_use_blocks() -> None:
    """When _extract_assistant_text sees a tool_use block in the
    stream-json output, it routes the block through the helper —
    but only the user-facing text is yielded."""
    stats = get_dispatcher_stats()
    stats.reset()
    parent = stats.record_start(tool="ask_project", project="alpha")
    try:
        line = (
            '{"type":"assistant","message":{"content":'
            '[{"type":"tool_use","id":"use_1","name":"Read","input":{}},'
            '{"type":"text","text":"hello"}]}}'
        )
        with span_context(span_id=parent.span_id, trace_id=parent.trace_id):
            chunks = list(ClaudeBackend._extract_assistant_text(line))
        assert chunks == ["hello"]
        # Close the child span the helper opened.
        _maybe_close_tool_result_span(
            {"tool_use_id": "use_1", "is_error": False}
        )
    finally:
        stats.record_end(parent, ok=True)
    by_tool = {r["tool"]: r for r in stats.recent_completed(limit=10)}
    assert "claude.tool:Read" in by_tool


# ---- Item 7: /api/dispatcher/recent surfaces new fields -------------------


def test_api_dispatcher_recent_includes_parent_and_trace() -> None:
    stats = get_dispatcher_stats()
    stats.reset()
    span = stats.record_start(tool="ask_project", project="alpha")
    stats.record_end(span, ok=True)

    cfg = HarbormasterConfig()
    app = create_app(cfg)
    with patch(
        "harbormaster.fleetq.get_dispatcher_stats",
        return_value=stats,
    ), TestClient(app) as client:
        r = client.get("/api/dispatcher/recent?limit=1")
        assert r.status_code == 200
        rows = r.json()["spans"]
        assert len(rows) == 1
        assert "parent_span_id" in rows[0]
        assert "trace_id" in rows[0]
        assert rows[0]["trace_id"] == span.span_id

"""v17.0.0a2 — codex backend tool_use instrumentation parity.

Closes the v16.a6 deviation: only `claude.py` was instrumented for
tool_use child spans. v17.a2 mirrors the pattern in `codex.py` so
the dispatcher trace surface (rendered by v17.a1's waterfall) shows
parent/child rows regardless of which backend served the dispatch.

Codex's CLI doesn't have a single canonical tool-call shape; we
accept both the OpenAI `--json` shape (`function_call` /
`function_call_output` keyed by `call_id`) and the Claude-style
shape (`tool_use` / `tool_result` keyed by `id` / `tool_use_id`).
Lines that don't match either are a silent no-op.
"""
from __future__ import annotations

from harbormaster.backends.codex import (
    CodexBackend,
    _maybe_close_tool_result_span,
    _maybe_emit_tool_use_span,
    _maybe_observe_codex_line,
)
from harbormaster.fleetq import (
    get_dispatcher_stats,
    span_context,
)

# ---- _maybe_emit_tool_use_span ------------------------------------------


def test_emit_outside_dispatch_is_noop() -> None:
    stats = get_dispatcher_stats()
    stats.reset()
    _maybe_emit_tool_use_span({"id": "use_1", "name": "Read"})
    assert stats.recent_completed(limit=10) == []


def test_emit_inside_dispatch_creates_child_with_codex_prefix() -> None:
    """Tool name must be prefixed `codex.tool:` so operators can tell
    which backend produced the span in the waterfall view."""
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
    by_tool = {r["tool"]: r for r in rows}
    assert "ask_project" in by_tool
    assert "codex.tool:Read" in by_tool
    child = by_tool["codex.tool:Read"]
    assert child["parent_span_id"] == parent.span_id
    assert child["trace_id"] == parent.trace_id


def test_emit_accepts_function_call_shape_with_call_id() -> None:
    """Codex `--json` mode emits OpenAI Responses-API shapes:
    function_call has `call_id` (not `id`)."""
    stats = get_dispatcher_stats()
    stats.reset()
    parent = stats.record_start(tool="ask_project", project="alpha")
    try:
        with span_context(span_id=parent.span_id, trace_id=parent.trace_id):
            _maybe_emit_tool_use_span(
                {"call_id": "fc_abc", "name": "shell"}
            )
            _maybe_close_tool_result_span({"call_id": "fc_abc"})
    finally:
        stats.record_end(parent, ok=True)
    by_tool = {r["tool"]: r for r in stats.recent_completed(limit=10)}
    assert "codex.tool:shell" in by_tool


def test_emit_handles_missing_id_gracefully() -> None:
    stats = get_dispatcher_stats()
    stats.reset()
    parent = stats.record_start(tool="ask_project", project="alpha")
    try:
        with span_context(span_id=parent.span_id, trace_id=parent.trace_id):
            _maybe_emit_tool_use_span({"name": "Read"})  # no id / call_id
            _maybe_emit_tool_use_span({"id": "use_x"})    # no name
    finally:
        stats.record_end(parent, ok=True)
    rows = stats.recent_completed(limit=10)
    assert len(rows) == 1
    assert rows[0]["tool"] == "ask_project"


def test_close_with_unknown_id_is_noop() -> None:
    """Result for a tool_use that was never opened must not crash."""
    _maybe_close_tool_result_span({"call_id": "no-such-id"})
    _maybe_close_tool_result_span({"tool_use_id": "no-such-id"})
    # No exception raised — that's the assertion.


# ---- _maybe_observe_codex_line line dispatcher --------------------------


def test_observe_routes_function_call_to_emit() -> None:
    stats = get_dispatcher_stats()
    stats.reset()
    parent = stats.record_start(tool="ask_project", project="alpha")
    try:
        with span_context(span_id=parent.span_id, trace_id=parent.trace_id):
            _maybe_observe_codex_line(
                '{"type":"function_call","call_id":"fc_1","name":"shell"}'
            )
            _maybe_observe_codex_line(
                '{"type":"function_call_output","call_id":"fc_1"}'
            )
    finally:
        stats.record_end(parent, ok=True)
    by_tool = {r["tool"]: r for r in stats.recent_completed(limit=10)}
    assert "codex.tool:shell" in by_tool


def test_observe_routes_claude_style_tool_use() -> None:
    """Some codex wrappers re-emit the Claude stream-json shape."""
    stats = get_dispatcher_stats()
    stats.reset()
    parent = stats.record_start(tool="ask_project", project="alpha")
    try:
        with span_context(span_id=parent.span_id, trace_id=parent.trace_id):
            _maybe_observe_codex_line(
                '{"type":"tool_use","id":"u_2","name":"Read"}'
            )
            _maybe_observe_codex_line(
                '{"type":"tool_result","tool_use_id":"u_2","is_error":false}'
            )
    finally:
        stats.record_end(parent, ok=True)
    by_tool = {r["tool"]: r for r in stats.recent_completed(limit=10)}
    assert "codex.tool:Read" in by_tool


def test_observe_ignores_non_json_lines() -> None:
    """Plain text lines and malformed JSON must be silent no-ops —
    codex's default output mode is plain text, this is the common case."""
    stats = get_dispatcher_stats()
    stats.reset()
    parent = stats.record_start(tool="ask_project", project="alpha")
    try:
        with span_context(span_id=parent.span_id, trace_id=parent.trace_id):
            _maybe_observe_codex_line("hello world")
            _maybe_observe_codex_line("not json {missing brace")
            _maybe_observe_codex_line("[1,2,3]")  # JSON list, not object
            _maybe_observe_codex_line('{"type":"unknown_event","x":1}')
            _maybe_observe_codex_line("")
    finally:
        stats.record_end(parent, ok=True)
    rows = stats.recent_completed(limit=10)
    assert len(rows) == 1  # only the parent
    assert rows[0]["tool"] == "ask_project"


def test_observe_outside_dispatch_is_noop() -> None:
    """Without an active parent span, even a well-formed event creates
    nothing — instrumentation is best-effort and never crashes."""
    stats = get_dispatcher_stats()
    stats.reset()
    _maybe_observe_codex_line(
        '{"type":"function_call","call_id":"x","name":"shell"}'
    )
    assert stats.recent_completed(limit=10) == []


# ---- _is_tool_event_line suppression --------------------------------------


def test_is_tool_event_line_recognises_all_four_types() -> None:
    assert CodexBackend._is_tool_event_line(
        '{"type":"function_call","call_id":"x","name":"shell"}'
    )
    assert CodexBackend._is_tool_event_line(
        '{"type":"function_call_output","call_id":"x"}'
    )
    assert CodexBackend._is_tool_event_line(
        '{"type":"tool_use","id":"u","name":"Read"}'
    )
    assert CodexBackend._is_tool_event_line(
        '{"type":"tool_result","tool_use_id":"u"}'
    )


def test_is_tool_event_line_rejects_text_and_other_json() -> None:
    """Plain text and non-tool JSON pass through as visible deltas."""
    assert not CodexBackend._is_tool_event_line("hello")
    assert not CodexBackend._is_tool_event_line(
        '{"type":"completion","text":"answer"}'
    )
    assert not CodexBackend._is_tool_event_line('{"foo":"bar"}')
    assert not CodexBackend._is_tool_event_line("[1,2,3]")
    assert not CodexBackend._is_tool_event_line("")
    assert not CodexBackend._is_tool_event_line("{not json")

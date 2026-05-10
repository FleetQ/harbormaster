"""v17.0.0a1 — trace waterfall renderer tests.

Closes the v16.a6 split: backend already emits hierarchical
span_start / span_end events (parent_span_id + trace_id); this phase
adds the template-side renderer that groups spans by trace_id,
indents children under parents, and bar-widths each span relative
to the trace's total window.

Test layers:

1. Page render: the new waterfall markup is present (data-* hooks,
   collapse buttons, attribute panels).
2. Hierarchy: a real dispatch flow lands in ``/api/dispatcher/recent``
   with parent_span_id + trace_id populated — the data the renderer
   consumes is well-formed end-to-end.
3. SSE append wiring: the script body still subscribes to
   ``/api/dispatcher/trace`` and the helper functions exist.

The Alpine factory + JS arithmetic are exercised at the template
level (string assertions) — the page-level Playwright bundle in
``test_smoke_bundle_v13`` keeps end-to-end DOM rendering covered.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from harbormaster.config import HarbormasterConfig, ProjectsConfig
from harbormaster.fleetq import (
    MCPDispatcher,
    get_dispatcher_stats,
    span_context,
)
from harbormaster.ui.app import create_app


@pytest.fixture
def waterfall_client(tmp_path: Path) -> TestClient:
    (tmp_path / "projects").mkdir(parents=True, exist_ok=True)
    cfg = HarbormasterConfig(
        projects=ProjectsConfig(glob=[str(tmp_path / "projects" / "*")]),
    )
    return TestClient(create_app(cfg))


@pytest.fixture(autouse=True)
def _reset_stats() -> None:
    get_dispatcher_stats().reset()


# ---- 1. Page render ------------------------------------------------------


def test_waterfall_markup_present(waterfall_client: TestClient) -> None:
    """The new renderer markup is reachable from the dispatcher page."""
    r = waterfall_client.get("/dispatcher")
    assert r.status_code == 200
    body = r.text
    # Top-level traces container (newest-first list).
    assert "data-trace-waterfall-list" in body
    # Per-trace collapsible header.
    assert "data-trace-toggle" in body
    # Per-trace span list (children of the trace).
    assert "data-trace-spans" in body
    # Per-span expand/collapse for the attribute panel.
    assert "data-span-toggle" in body
    # Span attribute panel (span_id / parent / trace).
    assert "data-span-attributes" in body
    # The renderer must read depth from the span row to indent.
    assert "data-depth" in body
    # The "Recent traces" header replaces the v9.0.0a3 single-row label.
    assert "Recent traces" in body
    # Active section preserved.
    assert "In-flight" in body


def test_waterfall_factory_preserved(waterfall_client: TestClient) -> None:
    """The Alpine factory name is the page contract (test was pinned
    in v9.0.0a3 — keep the contract). The renderer re-implements the
    factory body but keeps the name."""
    r = waterfall_client.get("/dispatcher")
    assert "traceWaterfall()" in r.text


def test_waterfall_helpers_present(waterfall_client: TestClient) -> None:
    """The waterfall arithmetic helpers must be in the script body so
    the template :style bindings resolve."""
    body = waterfall_client.get("/dispatcher").text
    assert "barOffsetPct" in body
    assert "barWidthPct" in body
    assert "traceDurationMs" in body
    assert "formatRel" in body
    # Grouping + tree-build helpers.
    assert "_groupIntoTraces" in body
    assert "_buildTrace" in body
    # Live append on SSE end event.
    assert "_appendCompleted" in body


def test_waterfall_keeps_sse_endpoints(waterfall_client: TestClient) -> None:
    """The renderer must still subscribe to the existing SSE feed and
    fetch the recent endpoint on first paint — backend was not
    changed in v17.a1."""
    body = waterfall_client.get("/dispatcher").text
    assert "/api/dispatcher/trace" in body
    assert "/api/dispatcher/recent" in body


# ---- 2. Hierarchy data shape end-to-end ---------------------------------


def test_recent_endpoint_carries_hierarchy_for_renderer(
    waterfall_client: TestClient,
) -> None:
    """The renderer requires every span row to carry parent_span_id +
    trace_id. v16.a6 added these but v17.a1 is the first consumer —
    pin the wire shape so the renderer can rely on it."""
    stats = get_dispatcher_stats()
    parent = stats.record_start(tool="ask_project", project="alpha")
    with span_context(span_id=parent.span_id, trace_id=parent.trace_id):
        child = stats.record_start(
            tool="claude.tool:Read",
            parent_span_id=parent.span_id,
        )
        stats.record_end(child, ok=True)
    stats.record_end(parent, ok=True)

    rows = waterfall_client.get("/api/dispatcher/recent?limit=10").json()["spans"]
    by_tool = {r["tool"]: r for r in rows}
    assert "ask_project" in by_tool
    assert "claude.tool:Read" in by_tool
    p = by_tool["ask_project"]
    c = by_tool["claude.tool:Read"]
    # Parent is a root: parent_span_id None, trace_id == own.
    assert p["parent_span_id"] is None
    assert p["trace_id"] == p["span_id"]
    # Child points at parent and shares the trace.
    assert c["parent_span_id"] == p["span_id"]
    assert c["trace_id"] == p["trace_id"]


def test_real_dispatch_lands_with_trace_id(
    waterfall_client: TestClient,
) -> None:
    """Sanity: a real MCPDispatcher.dispatch flow populates trace_id
    on the resulting recent_completed entry."""

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
        {
            "method": "tools/call",
            "params": {"name": "recall_qa", "arguments": {}},
        }
    ):
        pass

    rows = waterfall_client.get("/api/dispatcher/recent?limit=10").json()["spans"]
    assert len(rows) == 1
    assert rows[0]["trace_id"] is not None
    assert rows[0]["trace_id"] == rows[0]["span_id"]


# ---- 3. Collapse / expand wiring (Alpine attrs) -------------------------


def test_collapse_toggle_on_trace_header(waterfall_client: TestClient) -> None:
    """Trace header is a button with @click toggling `trace.collapsed`,
    and the spans list is bound to ``x-show="!trace.collapsed"``."""
    body = waterfall_client.get("/dispatcher").text
    assert 'trace.collapsed = !trace.collapsed' in body
    assert 'x-show="!trace.collapsed"' in body
    # The header reflects state via aria-expanded for accessibility.
    assert ":aria-expanded=\"!trace.collapsed\"" in body


def test_expand_toggle_on_span_attributes(waterfall_client: TestClient) -> None:
    """Each span row exposes a toggle that flips `span.expanded`,
    and the attribute panel is bound to ``x-show="span.expanded"``."""
    body = waterfall_client.get("/dispatcher").text
    assert 'span.expanded = !span.expanded' in body
    assert 'x-show="span.expanded"' in body

"""v21.0.9: friendly empty-states for the three "looks broken when zero"
surfaces on /network.

Issue reported 2026-05-12: a fresh harbormaster install with 0 MCP
calls in the last 1h shows three confusing surfaces — Timeline tab
renders an empty SVG, Inspector shows a grid of zeros, Stats tab
renders 5 unlabelled empty cells. Each looks like a broken
dashboard. v21.0.9 adds clear empty-state copy + a CTA where
applicable.

These tests pin the markup contract for the three new empty states
so a future refactor can't silently regress them.
"""
from __future__ import annotations

from pathlib import Path


def _read_template() -> str:
    return (
        Path(__file__).parent.parent.parent
        / "src" / "harbormaster" / "ui"
        / "templates" / "network.html"
    ).read_text(encoding="utf-8")


def test_timeline_has_in_window_empty_state() -> None:
    """The timeline view must show an empty-state when there are events
    but none in the selected window — previously it rendered an empty
    SVG with no explanation."""
    src = _read_template()
    assert 'data-empty-state="network.no-events-in-window"' in src
    assert 'No events in the' in src
    # CTA to widen the window when stuck on 1h.
    assert "Switch to 24h" in src
    # The CTA must update the timelineWindow state.
    assert "timelineWindow = '24h'" in src


def test_timeline_svg_gated_on_in_window_count() -> None:
    """The SVG itself must hide when timelineEventsTotal === 0, not
    just when events.length === 0. Previously the SVG rendered with
    all-zero bars whenever events existed at all, even if none fit
    the window."""
    src = _read_template()
    # Both the SVG and the counters footer flip on in-window total.
    assert 'x-show="timelineEventsTotal > 0"' in src


def test_timeline_empty_state_distinguishes_24h_case() -> None:
    """When the operator already widened to 24h and still has 0
    events, the CTA must disappear (there's no wider window) and the
    copy must point at running an MCP tool instead."""
    src = _read_template()
    # The "switch to 24h" CTA is gated on currently being on 1h.
    assert "x-show=\"timelineWindow === '1h'\"" in src
    # The fallback copy points at running a tool.
    assert "Run an MCP tool against a project to populate the timeline." in src


def test_inspector_has_no_recent_traffic_empty_state() -> None:
    """When the 1h stats endpoint returns total_calls=0, the Inspector
    must show an empty-state instead of three sections of zeros."""
    src = _read_template()
    assert 'data-empty-state="inspector.no-recent-traffic"' in src
    assert "No MCP calls in the last hour." in src
    # The Inspector empty-state mentions the wider-window options.
    assert "last 24h / 7d / all time" in src


def test_inspector_grid_hidden_when_total_calls_zero() -> None:
    """The three sections (Last 1h / By tool / Top projects) must hide
    when stats.total_calls === 0, replaced by the empty-state above."""
    src = _read_template()
    # Sections render only when stats hasn't loaded yet OR has nonzero.
    assert "!stats || stats.total_calls > 0" in src


def test_stats_tab_has_no_traffic_empty_state() -> None:
    """Stats tab must surface an empty-state when total_calls=0 instead
    of rendering 5 unlabelled empty cells."""
    src = _read_template()
    assert 'data-empty-state="stats.no-traffic-in-window"' in src
    assert "No MCP calls in the" in src
    # The copy must dynamically reflect the selected window.
    assert "window === 'all' ? 'recorded history' : 'last ' + window" in src


def test_stats_grid_hidden_when_total_calls_zero() -> None:
    """The 5-cell grid (`<dl class="grid grid-cols-2 md:grid-cols-5">`)
    must hide when total_calls=0 so the empty-state takes its place."""
    src = _read_template()
    # The visible-grid predicate matches the empty-state's inverse.
    assert 'x-show="stats && stats.total_calls > 0"' in src

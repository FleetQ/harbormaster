"""v19.0.0a3: context-aware inspector pane widgets.

Pins the structural invariants of the per-page `{% block inspector %}`
overrides added in a3 so future template edits don't accidentally
revert the right-pane to the static a1 placeholder.

Mirrors the test_v19_project_tabs.py pattern — pure template-source
assertions, no live server. Behavioural integration (auto-refresh
intervals, /api/* round-trips, Alpine reactivity) is covered by the
browser smoke runs against each page.
"""
from __future__ import annotations

from pathlib import Path

import pytest

TEMPLATES_DIR = (
    Path(__file__).parent.parent.parent
    / "src"
    / "harbormaster"
    / "ui"
    / "templates"
)


def _read(name: str) -> str:
    return (TEMPLATES_DIR / name).read_text()


def test_base_template_exposes_inspector_block() -> None:
    """base.html must define `{% block inspector %}` so per-page
    templates can override it. Without the block hook, every page would
    render the default placeholder regardless of overrides."""
    src = _read("base.html")
    assert "{% block inspector %}" in src, (
        "base.html missing inspector block hook"
    )
    # The block must live INSIDE the #inspector aside — otherwise the
    # override would render outside the right-pane container.
    inspector_aside_idx = src.find('id="inspector"')
    block_idx = src.find("{% block inspector %}")
    endblock_idx = src.find("{% endblock %}", block_idx)
    aside_close_idx = src.find("</aside>", inspector_aside_idx)
    assert inspector_aside_idx >= 0
    assert block_idx > inspector_aside_idx, (
        "inspector block must live inside the #inspector aside"
    )
    assert endblock_idx < aside_close_idx, (
        "inspector block must close BEFORE the #inspector aside closes"
    )
    # Default placeholder text is preserved so pages that decline to
    # override see something meaningful (rather than an empty pane).
    assert "No inspector widgets for this page" in src


@pytest.mark.parametrize(
    "template",
    [
        "dashboard.html",
        "project_detail.html",
        "network.html",
        "dispatcher_trace.html",
        "fan_out.html",
    ],
)
def test_each_page_overrides_inspector_block(template: str) -> None:
    """All five page templates must override the inspector block.
    Otherwise the right pane silently regresses to the default
    placeholder text from base.html."""
    src = _read(template)
    assert "{% block inspector %}" in src, (
        f"{template} missing inspector block override"
    )
    # data-tour-step="inspector-content" is the stable hook the v19
    # tour overlay uses to point at this region.
    assert 'data-tour-step="inspector-content"' in src, (
        f"{template} inspector block missing data-tour-step hook"
    )


def test_dashboard_inspector_renders_kpi_summary_and_activity_feed() -> None:
    """Dashboard inspector must contain (a) a KPI mirror dl and (b) an
    activity feed list bound to /api/network/events."""
    src = _read("dashboard.html")
    # KPI inspector factory + the four KPI fields.
    assert "function kpiInspector()" in src
    assert 'x-data="kpiInspector()"' in src
    for label in ("Projects", "Active embeds", "1h queries", "Bridge"):
        assert label in src
    # Activity feed factory + /api/network/events endpoint.
    assert "function activityFeed()" in src
    assert 'x-data="activityFeed()"' in src
    assert "/api/network/events?limit=10" in src
    # Both factories must auto-refresh — start() is the convention.
    assert "this._interval = setInterval" in src


def test_project_detail_inspector_renders_metadata_and_budget() -> None:
    """Project detail inspector must contain (a) metadata fields from
    the page's `project` context dict and (b) a budget section that
    fetches /api/projects/budget."""
    src = _read("project_detail.html")
    assert "function projectInspector(" in src
    # Metadata fields surfaced from ProjectInfo.as_dict.
    for label in (
        "last commit",
        "language",
        "host",
        "path",
        "serena memories",
        "CLAUDE.md",
    ):
        assert label in src, f"project inspector missing {label!r}"
    # Budget section + correct endpoint.
    assert "/api/projects/budget?host=" in src
    assert "Budget (24h)" in src
    # Tightest-cap axis surfaced — that's the operator's "what's at risk" pick.
    assert "tightest_cap_axis" in src


def test_network_inspector_renders_compact_stats_summary() -> None:
    """Network inspector must mirror /api/network/stats?window=1h with
    headline totals (total_calls / error_rate), by-tool breakdown,
    and top-projects list. The full stats panel stays in main."""
    src = _read("network.html")
    assert "function networkInspector()" in src
    assert "/api/network/stats?window=1h" in src
    # Headline cells + breakdown headers.
    for label in ("total calls", "error rate", "By tool", "Top projects"):
        assert label in src, f"network inspector missing {label!r}"
    # Pinned to 1h — the inspector window is intentionally fixed
    # (independent of the main panel's window selector).
    assert "window=1h" in src


def test_dispatcher_inspector_renders_in_flight_and_tool_summary() -> None:
    """Dispatcher inspector must surface in-flight counts +
    per-tool counters from /api/dispatcher/status."""
    src = _read("dispatcher_trace.html")
    assert "function dispatcherInspector()" in src
    assert "/api/dispatcher/status" in src
    for label in ("active workers", "queue depth", "last dispatch", "By tool"):
        assert label in src, f"dispatcher inspector missing {label!r}"
    # Per-tool row formatter — the operator wants in_flight + done at a glance.
    assert "in_flight" in src
    assert "total_completed" in src


def test_fan_out_inspector_minimal_context_help() -> None:
    """Fan-out inspector is intentionally minimal — context help + links
    to related tools. No data-fetching factory; the form already owns
    the main column."""
    src = _read("fan_out.html")
    # Verify the inspector block was overridden (not just inherited
    # default placeholder).
    blocks = src.count("{% block inspector %}")
    assert blocks == 1
    # About + Related sections.
    assert "About fan-out" in src
    assert "Related" in src
    # Links to dispatcher + network — operator-facing related tools.
    assert 'href="/dispatcher"' in src
    assert 'href="/network"' in src


@pytest.mark.parametrize(
    "template,expected_class",
    [
        ("dashboard.html", "border-border"),
        ("project_detail.html", "border-border"),
        ("network.html", "border-border"),
        ("dispatcher_trace.html", "border-border"),
    ],
)
def test_inspector_blocks_use_real_tailwind_v4_tokens(
    template: str, expected_class: str,
) -> None:
    """Each inspector block must use tokens that ACTUALLY exist in
    tailwind.input.css's `@theme` block — `border-border`,
    `text-foreground-muted`, `text-foreground-subtle` etc.

    Lesson from a2: the spec referenced `border-muted` / `text-secondary`
    which DON'T exist in the project's @theme. Pin against regression.
    """
    src = _read(template)
    block_idx = src.find("{% block inspector %}")
    assert block_idx >= 0
    end_idx = src.find("{% endblock %}", block_idx)
    assert end_idx > block_idx
    inspector_block = src[block_idx:end_idx]
    assert expected_class in inspector_block, (
        f"{template} inspector block missing {expected_class!r}"
    )
    # Forbidden tokens — these don't exist in @theme, so they would
    # silently render as no-style.
    forbidden = ("border-muted", "text-secondary", "bg-primary")
    for tok in forbidden:
        assert tok not in inspector_block, (
            f"{template} inspector block uses non-existent token {tok!r}"
        )

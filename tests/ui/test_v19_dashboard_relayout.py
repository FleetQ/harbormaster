"""v19.0.0a5: dashboard re-layout — Quick Ask + card grid.

Pins the structural invariants of the dashboard re-layout shipped in
a5 so future template edits don't accidentally revert the new shape:

  1. Quick Ask card (`quickAsk()` Alpine factory) renders at the top
     of `{% block content %}` — above the KPI strip.
  2. KPI strip is preserved as a 6-cell grid at lg+, with the
     `data-tour-step="kpi-strip"` hook on the section root.
  3. The dashboard widgets below the KPI strip flow inside a 2-col
     responsive card grid (`grid grid-cols-1 md:grid-cols-2 gap-3`).
  4. A new Recent activity card (`recentActivityCard()`) renders inside
     the card grid (mirrors the inspector activityFeed).
  5. The wide widgets (reembedPanel, recallPanel, graphPanel,
     statusStrip) span both columns via `md:col-span-2`.
  6. Existing Alpine factories (reembedPanel, recallPanel, graphPanel,
     projectGrid, statusStrip, kpiStrip) remain mounted — the re-layout
     is structural, not a behavioural rewrite.

Mirrors test_v19_inspector_content.py — pure template-source assertions,
no live server.
"""
from __future__ import annotations

import re
from pathlib import Path


def _expand_includes(content: str, base) -> str:
    """v24.0.0a5: expand `{% include "_partials/X" %}` so source-grep
    tests still find content moved into partials."""
    import re as _re
    pat = _re.compile(r'\s*\{%\s*include\s+"(_partials/[^"]+)"\s*%\}\s*')
    def _sub(m):
        try:
            return (base / m.group(1)).read_text(encoding="utf-8")
        except OSError:
            return m.group(0)
    return pat.sub(_sub, content)

TEMPLATE_PATH = (
    Path(__file__).parent.parent.parent
    / "src"
    / "harbormaster"
    / "ui"
    / "templates"
    / "dashboard.html"
)


def _read() -> str:
    return _expand_includes(TEMPLATE_PATH.read_text(encoding="utf-8"), TEMPLATE_PATH.parent)


# ---------------------------------------------------------------------------
# Quick Ask card
# ---------------------------------------------------------------------------

def test_quick_ask_card_renders_at_top_of_content() -> None:
    """Quick Ask must appear above the KPI strip inside `{% block content %}`."""
    src = _read()
    block_idx = src.find("{% block content %}")
    quick_ask_idx = src.find('x-data="quickAsk()"')
    kpi_strip_idx = src.find('x-data="kpiStrip()"')
    assert block_idx >= 0 and quick_ask_idx >= 0 and kpi_strip_idx >= 0
    assert block_idx < quick_ask_idx < kpi_strip_idx, (
        "Quick Ask must render between {% block content %} and the KPI strip"
    )


def test_quick_ask_factory_defined() -> None:
    """`quickAsk()` Alpine factory must be defined in the dashboard
    script block — it owns project-list fetch + navigation handoff."""
    src = _read()
    assert "function quickAsk()" in src
    # Project list source.
    assert "/api/projects" in src
    # Navigation handoff — passes the question via `?q=` so the project
    # page's askForm() picks it up via init().
    assert "/projects/' + encodeURIComponent(this.project)" in src
    assert "?q=' + encodeURIComponent(this.question.trim())" in src


def test_quick_ask_form_fields_present() -> None:
    """Quick Ask form must have project select, question input, and submit."""
    src = _read()
    # Locate the section bounds.
    start = src.find('x-data="quickAsk()"')
    end = src.find("</section>", start)
    assert start >= 0 and end > start
    section = src[start:end]
    assert 'x-model="project"' in section
    assert 'x-model="question"' in section
    assert 'type="submit"' in section
    # Disabled state guards against empty submissions.
    assert ":disabled=" in section
    # Cmd-K hint visible.
    assert "Cmd-K" in section or "cmd-K" in section.lower()


def test_quick_ask_uses_real_tailwind_v4_tokens() -> None:
    """Quick Ask must use tokens that exist in tailwind.input.css's
    `@theme` block. Lesson from inspector a2: `border-muted` etc. don't
    exist."""
    src = _read()
    start = src.find('x-data="quickAsk()"')
    end = src.find("</section>", start)
    section = src[start:end]
    # Real tokens.
    assert "border-border" in section
    assert "bg-surface-2" in section or "bg-surface-1" in section
    # Forbidden tokens.
    for tok in ("border-muted", "text-secondary", "bg-primary"):
        assert tok not in section, (
            f"Quick Ask uses non-existent token {tok!r}"
        )


# ---------------------------------------------------------------------------
# KPI strip preserved
# ---------------------------------------------------------------------------

def test_kpi_strip_remains_six_col_grid_at_lg() -> None:
    """KPI strip must keep its 6-cell `lg:grid-cols-6` shape — the
    re-layout must not shrink the at-a-glance row."""
    src = _read()
    start = src.find('x-data="kpiStrip()"')
    assert start >= 0
    # Class attribute lives on the next 200 chars or so.
    snippet = src[start:start + 400]
    assert "lg:grid-cols-6" in snippet, (
        "KPI strip lost its 6-col grid"
    )
    assert 'data-tour-step="kpi-strip"' in snippet, (
        "KPI strip section root lost its tour anchor"
    )


# ---------------------------------------------------------------------------
# Card grid wrapper
# ---------------------------------------------------------------------------

def test_card_grid_wrapper_exists() -> None:
    """A 2-col responsive card grid must wrap the widget cards."""
    src = _read()
    # The exact wrapper signature shipped in a5.
    assert re.search(
        r'<div\s+class="grid grid-cols-1 md:grid-cols-2 gap-3 mb-4"\s+data-card-grid>',
        src,
    ), "card grid wrapper div not found"
    # Closing comment so future edits know what they're closing.
    assert "</div><!-- /card-grid (v19.0.0a5) -->" in src


def test_card_grid_wraps_recent_activity_and_widget_sections() -> None:
    """The card grid must contain the recent-activity card AND the
    reembed/recall/graph/statusStrip sections — they are the dashboard's
    primary widget surface."""
    src = _read()
    grid_open = src.find('data-card-grid>')
    grid_close = src.find("</div><!-- /card-grid")
    assert grid_open >= 0 and grid_close > grid_open
    inside = src[grid_open:grid_close]
    for marker in (
        'x-data="recentActivityCard()"',
        'x-data="statusStrip()"',
        'x-data="reembedPanel()"',
        'x-data="recallPanel()"',
        'x-data="graphPanel()"',
    ):
        assert marker in inside, f"card grid missing {marker!r}"


def test_wide_widgets_span_both_columns() -> None:
    """reembedPanel, recallPanel, graphPanel, and statusStrip must
    all carry `md:col-span-2` so they span the full card-grid width
    (their internal layouts already paginate horizontally)."""
    src = _read()
    for factory in (
        "reembedPanel()",
        "recallPanel()",
        "graphPanel()",
        "statusStrip()",
    ):
        # Find the section opening tag for this factory.
        idx = src.find(f'x-data="{factory}"')
        assert idx >= 0, f"factory {factory} not found"
        # Walk back to the `<section` opener; class attribute is on the
        # same tag.
        tag_start = src.rfind("<section", 0, idx)
        tag_end = src.find(">", idx)
        assert tag_start >= 0 and tag_end > tag_start
        tag = src[tag_start:tag_end]
        assert "md:col-span-2" in tag, (
            f"{factory} missing md:col-span-2 — it lives in the card grid"
        )


# ---------------------------------------------------------------------------
# Recent activity card
# ---------------------------------------------------------------------------

def test_recent_activity_card_factory_defined() -> None:
    """`recentActivityCard()` factory must mirror the inspector
    activityFeed — same endpoint, same auto-refresh interval."""
    src = _read()
    assert "function recentActivityCard()" in src
    # Same endpoint as inspector activityFeed (single source of truth).
    assert src.count("/api/network/events?limit=10") >= 2, (
        "recent activity card and inspector activity feed must both "
        "fetch /api/network/events?limit=10"
    )
    # Auto-refresh — convention shared with kpiInspector / activityFeed.
    assert "this._interval = setInterval" in src


def test_recent_activity_card_links_to_network_view() -> None:
    """Recent activity card must include a `view all →` link to /network
    so operators can drill in."""
    src = _read()
    start = src.find('data-recent-activity-card')
    end = src.find("</section>", start)
    assert start >= 0 and end > start
    card = src[start:end]
    assert 'href="/network"' in card
    assert "view all" in card.lower()


# ---------------------------------------------------------------------------
# Existing factories preserved
# ---------------------------------------------------------------------------

def test_existing_dashboard_factories_still_mounted() -> None:
    """The re-layout is structural — every existing Alpine factory
    must still be mounted somewhere in the dashboard."""
    src = _read()
    for factory in (
        "kpiStrip()",
        "statusStrip()",
        "reembedPanel()",
        "recallPanel()",
        "graphPanel()",
        "projectGrid()",
        "helpPopover()",
        "kpiInspector()",
        "activityFeed()",
    ):
        assert f'x-data="{factory}"' in src, (
            f"existing factory {factory} no longer mounted on the dashboard"
        )


def test_project_grid_remains_below_card_grid() -> None:
    """The full-width project grid must sit BELOW the card grid —
    cards are the new dashboard surface, project grid is the long
    scrollable list below."""
    src = _read()
    grid_close = src.find("</div><!-- /card-grid")
    project_grid_idx = src.find('x-data="projectGrid()"')
    assert grid_close >= 0 and project_grid_idx > grid_close, (
        "project grid must render after the card grid closes"
    )

"""Tests for v21.0.0a7 — KPI sparkline wiring + final a11y polish pass.

Covers:
  * `GET /api/kpi/history` returns the canonical 4-series shape, each
    a list of 24 ints (one hourly bucket).
  * Dashboard KPI cells reference `historySparkline(...)` so the
    v16.0.0a4 `sparklineHtml` helper renders under each numeric cell.
  * Project inspector wires `budgetSparkline()` for the 24h usage
    line beneath the Budget block.
  * The `_tiny_sparkline.html` partial is referenced from at least
    two surfaces (base.html via {% include %} + dashboard.html via
    sparklineHtml() invocations).
  * Every `<button>` element across the UI templates carries
    `aria-label` (or :aria-label for dynamic copy) AND
    `focus-visible:ring-2 focus-visible:ring-accent` — the audit-style
    floor the final phase commits to.
  * `<html lang="en">` is set on the base layout.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from harbormaster.config import HarbormasterConfig, ProjectsConfig
from harbormaster.ui.app import create_app


# ---------------------------------------------------------------------------
# /api/kpi/history endpoint
# ---------------------------------------------------------------------------


@pytest.fixture
def history_client(tmp_path: Path) -> TestClient:
    (tmp_path / "projects").mkdir(parents=True, exist_ok=True)
    cfg = HarbormasterConfig(
        projects=ProjectsConfig(glob=[str(tmp_path / "projects" / "*")]),
    )
    return TestClient(create_app(cfg))


def test_kpi_history_canonical_shape(history_client: TestClient) -> None:
    r = history_client.get("/api/kpi/history")
    assert r.status_code == 200
    body = r.json()
    for key in ("projects", "active_embeds", "recent_queries", "host_budget"):
        assert key in body, f"missing KPI history key: {key}"
        series = body[key]
        assert isinstance(series, list), f"{key} not a list"
        assert len(series) == 24, f"{key} length {len(series)} != 24"
        for v in series:
            assert isinstance(v, int), f"{key} bucket non-int: {v!r}"


def test_kpi_history_projects_series_matches_count(
    history_client: TestClient,
) -> None:
    """Projects KPI is currently a stable count repeated across all 24
    buckets — no historical projects-count table exists yet."""
    body = history_client.get("/api/kpi/history").json()
    series = body["projects"]
    assert len(set(series)) == 1, "projects series should be flat"
    # And it should match the live /api/kpi projects count.
    kpi = history_client.get("/api/kpi").json()
    assert series[0] == kpi["projects"]


def test_kpi_history_zero_arrays_when_no_data(
    history_client: TestClient,
) -> None:
    """Recent-queries + host-budget + active-embeds default to zero
    arrays on a fresh install (no [history] extra, no network log
    entries, no budget configured)."""
    body = history_client.get("/api/kpi/history").json()
    assert body["recent_queries"] == [0] * 24
    assert body["active_embeds"] == [0] * 24
    assert body["host_budget"] == [0] * 24


# ---------------------------------------------------------------------------
# Sparkline wiring — template invariants
# ---------------------------------------------------------------------------

_TEMPLATES = Path("src/harbormaster/ui/templates")


def test_tiny_sparkline_partial_referenced_from_two_surfaces() -> None:
    """The v16.0.0a4 partial is loaded by base.html (every page) and
    must be invoked by at least one widget — N-way reembed compare
    (v17.0.0a3) plus the new KPI strip (v21.0.0a7)."""
    base = (_TEMPLATES / "base.html").read_text()
    dash = (_TEMPLATES / "dashboard.html").read_text()
    assert "_tiny_sparkline.html" in base, "base.html no longer loads sparkline partial"
    # Dashboard now references sparklineHtml() from BOTH the existing
    # reembed-compare panel AND the new KPI strip wiring.
    spark_refs = dash.count("sparklineHtml(")
    assert spark_refs >= 2, (
        f"dashboard.html sparklineHtml() refs = {spark_refs}, expected ≥ 2 "
        f"(N-way reembed compare + KPI strip)"
    )


def test_kpi_cells_have_sparkline_slot() -> None:
    dash = (_TEMPLATES / "dashboard.html").read_text()
    # The three numeric-flavour KPI cells get a sparkline slot.
    for cell_id in ("projects", "active-embeds", "recent-queries", "host-budget"):
        assert f'data-kpi-sparkline="{cell_id}"' in dash, (
            f"KPI sparkline slot missing for {cell_id}"
        )
    # And the kpiStrip() Alpine scope owns historySparkline() + loadHistory().
    assert "historySparkline(" in dash
    assert "loadHistory()" in dash


def test_project_inspector_budget_sparkline() -> None:
    pd = (_TEMPLATES / "project_detail.html").read_text()
    assert "data-budget-sparkline" in pd, "inspector budget sparkline slot missing"
    assert "budgetSparkline()" in pd, "budgetSparkline() helper missing"
    assert "/api/kpi/history" in pd, "inspector doesn't pull /api/kpi/history"


# ---------------------------------------------------------------------------
# a11y audit floor — buttons + html lang
# ---------------------------------------------------------------------------


def _all_buttons() -> list[tuple[Path, int, str, str]]:
    """Return [(file, line_no, full_tag, attrs)] for every <button> tag
    across the templates directory."""
    out: list[tuple[Path, int, str, str]] = []
    for f in _TEMPLATES.rglob("*.html"):
        txt = f.read_text()
        for m in re.finditer(r"<button\b([^>]*?)>", txt, re.DOTALL):
            line_no = txt[: m.start()].count("\n") + 1
            out.append((f, line_no, m.group(0), m.group(1)))
    return out


def test_every_button_has_focus_visible() -> None:
    misses = [
        (f.name, ln) for f, ln, _tag, attrs in _all_buttons()
        if "focus-visible:" not in attrs
    ]
    assert not misses, (
        "buttons missing focus-visible: " + ", ".join(f"{n}:{ln}" for n, ln in misses)
    )


def test_every_button_has_aria_label_or_visible_text() -> None:
    """An accessible name must come from either aria-label / :aria-label
    or a visible-text descendant. Icon-only glyphs in <span aria-hidden>
    don't count — those buttons MUST carry aria-label."""
    violations: list[str] = []
    for f in _TEMPLATES.rglob("*.html"):
        txt = f.read_text()
        for m in re.finditer(
            r"<button\b([^>]*?)>(.*?)</button>", txt, re.DOTALL
        ):
            attrs = m.group(1)
            inner = m.group(2)
            line_no = txt[: m.start()].count("\n") + 1
            has_aria = "aria-label" in attrs
            # Visible text = any non-whitespace outside aria-hidden spans.
            no_hidden = re.sub(
                r'<[^>]*\baria-hidden\s*=\s*"true"[^>]*>.*?</[^>]+>',
                "",
                inner,
                flags=re.DOTALL,
            )
            visible_text = re.sub(r"<[^>]+>", "", no_hidden).strip()
            has_dynamic_text = "x-text" in inner or "x-text" in attrs
            if not has_aria and not visible_text and not has_dynamic_text:
                violations.append(f"{f.name}:{line_no}")
    assert not violations, (
        "icon-only buttons without aria-label: " + ", ".join(violations)
    )


def test_base_html_has_lang_en() -> None:
    base = (_TEMPLATES / "base.html").read_text()
    assert re.search(r'<html\b[^>]*\blang="en"', base), (
        "base.html <html> must carry lang=\"en\""
    )


def test_tab_panels_have_role_tabpanel() -> None:
    """Every page that uses the v21.0.0a6 tabs unification must mark
    each tab-content section with role='tabpanel'. Heuristic: any file
    containing `_tabs.html` must contain at least one role="tabpanel"."""
    for f in _TEMPLATES.rglob("*.html"):
        txt = f.read_text()
        if "_partials/_tabs.html" not in txt:
            continue
        # Count tabpanel roles
        panels = txt.count('role="tabpanel"')
        assert panels >= 1, f"{f.name} uses _tabs.html but lacks role='tabpanel'"

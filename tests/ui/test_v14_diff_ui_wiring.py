"""v14.0.0a3 — diff-UI surface wiring on memory editor + reembed table.

Server-side endpoints (`format=html` for memory diff,
`/api/history/reembed/runs/diff`) ship in v13.a3 and have their own
tests. These tests check the *UI* wiring that consumes them did not
regress.

Two surfaces:

  - project_detail.html: memory editor diff panel exposes a
    Unified / Side-by-side toggle and the toggle calls loadDiff with
    a `diffFormat` flag that translates to `format=html`.
  - dashboard.html: the reembed history table grows a per-row Diff
    button and a delta panel that consumes the parity endpoint's
    JSON shape.
"""
from __future__ import annotations

from pathlib import Path

TEMPLATE_DIR = (
    Path(__file__).parent.parent.parent
    / "src"
    / "harbormaster"
    / "ui"
    / "templates"
)


def _expand_includes(content: str, base: Path) -> str:
    """v24.0.0a5: expand `{% include \"_partials/X\" %}` lines so
    source-grep tests still find content moved into partials."""
    import re as _re
    pat = _re.compile(r'\s*\{%\s*include\s+"(_partials/[^"]+)"\s*%\}\s*')
    def _sub(m):
        try:
            return (base / m.group(1)).read_text(encoding="utf-8")
        except OSError:
            return m.group(0)
    return pat.sub(_sub, content)


def _read(name: str) -> str:
    return _expand_includes((TEMPLATE_DIR / name).read_text(encoding="utf-8"), TEMPLATE_DIR)


# -- project_detail.html: memory diff toggle ---------------------------


def test_project_detail_has_diff_format_toggle_buttons() -> None:
    body = _read("project_detail.html")
    # Two toggle buttons — Unified and Side-by-side — wired to set
    # diffFormat and call loadDiff.
    assert "diffFormat = 'unified'" in body
    assert "diffFormat = 'html'" in body
    assert "Unified" in body
    assert "Side-by-side" in body


def test_project_detail_loaddiff_appends_format_html_when_html_selected() -> None:
    """loadDiff must include `&format=html` only when html is active."""
    body = _read("project_detail.html")
    # The conditional that decides whether to append format=html.
    assert "this.diffFormat === 'html' ? '&format=html' : ''" in body


def test_project_detail_diffhtml_state_initialised() -> None:
    body = _read("project_detail.html")
    assert "diffFormat: 'unified'" in body
    assert "diffHtml: ''" in body


def test_project_detail_diffhtml_rendered_via_x_html() -> None:
    """Side-by-side branch must use x-html (not x-text) to render the
    server-side HtmlDiff table. Server already sanitises."""
    body = _read("project_detail.html")
    assert 'x-html="diffHtml"' in body


# -- dashboard.html: reembed Diff button ------------------------------


def test_dashboard_reembed_table_has_diff_button() -> None:
    body = _read("dashboard.html")
    # The Diff button column exists and calls loadRunDiff(r).
    assert "loadRunDiff(r)" in body
    # Hidden on the very first row (no prior run to diff against).
    assert 'x-show="runs.indexOf(r) > 0"' in body


def test_dashboard_load_run_diff_calls_v13_parity_endpoint() -> None:
    body = _read("dashboard.html")
    # The endpoint URL with index-based from / to query params.
    assert "/api/history/reembed/runs/diff" in body
    assert "?from=${idx - 1}&to=${idx}" in body


def test_dashboard_diff_panel_renders_v13_delta_keys() -> None:
    """Run-diff panel renders the exact field names from the v13.a3
    payload: duration_seconds, total, succeeded, failed, cancelled,
    model_changed."""
    body = _read("dashboard.html")
    for key in (
        "duration_seconds",
        "succeeded",
        "failed",
        "cancelled",
        "model_changed",
    ):
        assert f"runDiff.delta?.{key}" in body, f"missing key: {key}"


def test_dashboard_format_delta_has_leading_sign() -> None:
    body = _read("dashboard.html")
    # The helper that prefixes positive deltas with '+'.
    assert "formatDelta(n)" in body
    assert "(n > 0 ? '+' : '')" in body


def test_dashboard_diff_panel_starts_closed() -> None:
    body = _read("dashboard.html")
    # The panel is gated on runDiffOpen; default false at init.
    assert "runDiffOpen: false" in body
    assert 'x-show="runDiffOpen"' in body

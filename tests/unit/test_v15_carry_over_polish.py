"""v15.0.0a6 — per-project markdown config + dashboard tour wizard."""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from harbormaster.config import (
    HarbormasterConfig,
    MarkdownConfig,
    ProjectsConfig,
)
from harbormaster.ui import create_app
from harbormaster.ui.markdown import render_safe, resolve_markdown_strict

TEMPLATE_DIR = (
    Path(__file__).parent.parent.parent
    / "src"
    / "harbormaster"
    / "ui"
    / "templates"
)


def _read_template(name: str) -> str:
    return (TEMPLATE_DIR / name).read_text(encoding="utf-8")


# -- MarkdownConfig schema --------------------------------------


def test_markdown_config_default_is_strict() -> None:
    cfg = MarkdownConfig()
    assert cfg.strict is True


def test_markdown_config_accepts_non_strict() -> None:
    cfg = MarkdownConfig(strict=False)
    assert cfg.strict is False


def test_harbormaster_config_includes_markdown_section() -> None:
    cfg = HarbormasterConfig()
    assert isinstance(cfg.markdown, MarkdownConfig)
    assert cfg.markdown.strict is True


# -- render_safe respects strict flag ---------------------------


def test_render_safe_strict_strips_span() -> None:
    """v11.0.0a3 allowlist: <span> is NOT in the strict set."""
    html = render_safe("<span>foo</span> bar", strict=True)
    # bleach strips the span tag (text remains).
    assert "<span" not in html
    assert "foo" in html


def test_render_safe_non_strict_keeps_span_kbd_mark() -> None:
    md = "Press <kbd>Cmd</kbd> + <kbd>K</kbd>; <mark>highlight</mark>; <span>x</span>"
    html = render_safe(md, strict=False)
    assert "<kbd>" in html
    assert "<mark>" in html
    assert "<span>" in html


def test_render_safe_non_strict_still_strips_script() -> None:
    """Strict flag widens TAGS only — script-injection rails unchanged."""
    html = render_safe("<script>alert(1)</script>plain", strict=False)
    assert "<script" not in html
    assert "alert(1)" not in html or "&lt;script" not in html


def test_render_safe_default_is_strict() -> None:
    """Backwards-compat: render_safe(text) without kwarg = strict."""
    html_a = render_safe("<span>x</span>")
    html_b = render_safe("<span>x</span>", strict=True)
    assert html_a == html_b
    assert "<span" not in html_a


# -- resolve_markdown_strict per-project loader ----------------


def test_resolve_markdown_strict_returns_global_when_no_project(
    tmp_path: Path,
) -> None:
    assert resolve_markdown_strict(project_path=None, global_strict=True) is True
    assert resolve_markdown_strict(project_path=None, global_strict=False) is False


def test_resolve_markdown_strict_returns_global_when_no_override(
    tmp_path: Path,
) -> None:
    p = tmp_path / "alpha"
    p.mkdir()
    assert resolve_markdown_strict(project_path=p, global_strict=True) is True


def test_resolve_markdown_strict_per_project_overrides_global(
    tmp_path: Path,
) -> None:
    p = tmp_path / "alpha"
    p.mkdir()
    (p / ".harbormaster.toml").write_text(
        "[markdown]\nstrict = false\n", encoding="utf-8",
    )
    assert resolve_markdown_strict(project_path=p, global_strict=True) is False


def test_resolve_markdown_strict_per_project_can_re_enable(
    tmp_path: Path,
) -> None:
    p = tmp_path / "alpha"
    p.mkdir()
    (p / ".harbormaster.toml").write_text(
        "[markdown]\nstrict = true\n", encoding="utf-8",
    )
    assert resolve_markdown_strict(project_path=p, global_strict=False) is True


def test_resolve_markdown_strict_handles_garbage_toml(
    tmp_path: Path,
) -> None:
    """Failures fall through to the global value — never raise."""
    p = tmp_path / "alpha"
    p.mkdir()
    (p / ".harbormaster.toml").write_text("not = valid = toml\n")
    assert resolve_markdown_strict(project_path=p, global_strict=True) is True


def test_resolve_markdown_strict_handles_non_bool_value(
    tmp_path: Path,
) -> None:
    p = tmp_path / "alpha"
    p.mkdir()
    (p / ".harbormaster.toml").write_text(
        '[markdown]\nstrict = "yes"\n', encoding="utf-8",
    )
    # Wrong type → falls through to the global value.
    assert resolve_markdown_strict(project_path=p, global_strict=False) is False


# -- /api/render-markdown wires through ------------------------


def test_render_markdown_endpoint_default_is_strict() -> None:
    cfg = HarbormasterConfig()
    app = create_app(cfg)
    with TestClient(app) as client:
        r = client.post(
            "/api/render-markdown",
            json={"text": "<span>foo</span>"},
        )
        assert r.status_code == 200
        assert "<span" not in r.text
        assert "foo" in r.text


def test_render_markdown_endpoint_global_non_strict() -> None:
    cfg = HarbormasterConfig(markdown=MarkdownConfig(strict=False))
    app = create_app(cfg)
    with TestClient(app) as client:
        r = client.post(
            "/api/render-markdown",
            json={"text": "<span>foo</span>"},
        )
        assert r.status_code == 200
        assert "<span>" in r.text


def test_render_markdown_endpoint_per_project_override(
    tmp_path: Path,
) -> None:
    """Per-project .harbormaster.toml overrides the global value."""
    project_dir = tmp_path / "alpha"
    project_dir.mkdir()
    (project_dir / ".git").mkdir()
    (project_dir / ".harbormaster.toml").write_text(
        "[markdown]\nstrict = false\n", encoding="utf-8",
    )
    cfg = HarbormasterConfig(
        # Global is strict; per-project flips it.
        markdown=MarkdownConfig(strict=True),
        projects=ProjectsConfig(glob=[f"{tmp_path}/*"]),
    )
    app = create_app(cfg)
    with TestClient(app) as client:
        r = client.post(
            "/api/render-markdown",
            json={"text": "<span>foo</span>", "project": "alpha"},
        )
        assert r.status_code == 200
        # Per-project flipped to non-strict — span tag survives.
        assert "<span>" in r.text


def test_render_markdown_endpoint_unknown_project_falls_through() -> None:
    """Unknown project name silently uses the global value."""
    cfg = HarbormasterConfig(markdown=MarkdownConfig(strict=True))
    app = create_app(cfg)
    with TestClient(app) as client:
        r = client.post(
            "/api/render-markdown",
            json={"text": "<span>foo</span>", "project": "no-such-project"},
        )
        assert r.status_code == 200
        # Global strict still applies.
        assert "<span" not in r.text


# -- Dashboard tour wizard UI wiring ---------------------------


def test_dashboard_template_has_tour_wizard_state() -> None:
    body = _read_template("dashboard.html")
    assert "function dashboardTour()" in body
    assert "hm-tour-completed" in body
    # Step count matches the brief (5 steps).
    assert "Step ${stepIndex + 1} of ${steps.length}" in body


def test_dashboard_template_tour_steps_match_brief() -> None:
    body = _read_template("dashboard.html")
    # All 5 anchor selectors from the brief.
    assert "data-kpi-cell=\"projects\"" in body
    assert "#hm-sidebar" in body
    assert 'section[x-data^="askForm"]' in body
    assert "x-data=\"commandPalette()\"" in body
    assert 'section[x-data^="memoriesPanel"]' in body


def test_dashboard_template_tour_gated_by_localstorage() -> None:
    body = _read_template("dashboard.html")
    # The gating logic checks localStorage AND the ?tour=1 force flag.
    assert "localStorage.getItem('hm-tour-completed')" in body
    assert "params.get('tour') === '1'" in body


def test_dashboard_template_tour_complete_writes_localstorage() -> None:
    body = _read_template("dashboard.html")
    assert "localStorage.setItem('hm-tour-completed', '1')" in body


def test_dashboard_template_tour_skip_does_not_mark_complete() -> None:
    body = _read_template("dashboard.html")
    # The dismiss() comment explains the design decision.
    assert "Don't mark \"completed\" on skip" in body


# Tiny pytest import guard so tooling doesn't flag the module.
def test_pytest_imported() -> None:
    assert pytest.__version__

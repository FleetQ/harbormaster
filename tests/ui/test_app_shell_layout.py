"""v19.0.0a1: 3-column workspace shell — fixed topbar + sticky
240px nav + fluid main + sticky 320px inspector (collapsible to 0).

Pins the structural invariants of the new shell so future template
edits don't accidentally regress to the old v10 fixed-sidebar layout
or the pre-v10 `min-h-screen` flow layout.
"""
from __future__ import annotations

from pathlib import Path

import pytest

TEMPLATE_DIR = (
    Path(__file__).parent.parent.parent
    / "src"
    / "harbormaster"
    / "ui"
    / "templates"
)


def _read(name: str) -> str:
    return (TEMPLATE_DIR / name).read_text()


def test_body_uses_min_h_screen_grid_shell() -> None:
    """v19 abandons the v10 `h-screen overflow-hidden` body in favor
    of a `min-h-screen` body whose inner grid claims its own scroll
    contexts per column. Sentinel: the v10 class must be gone."""
    src = _read("base.html")
    assert 'class="bg-surface-1 text-foreground min-h-screen"' in src
    assert 'class="h-screen overflow-hidden"' not in src


def test_topbar_is_fixed_with_id_and_height() -> None:
    src = _read("base.html")
    assert 'id="hm-topbar"' in src
    assert "fixed top-0" in src
    assert "h-12" in src


def test_grid_has_three_columns_with_inspector_toggle() -> None:
    """The shell is a CSS grid: 240px nav + 1fr main + 320px inspector
    (or 0 when collapsed). Both column templates must be present so
    the inspector-collapse toggle has both states to swap between."""
    src = _read("base.html")
    assert "grid-cols-[240px_1fr_320px]" in src
    assert "grid-cols-[240px_1fr_0]" in src
    assert 'pt-12 grid' in src


def test_sidebar_is_sticky_under_topbar() -> None:
    src = _read("base.html")
    assert 'id="hm-sidebar"' in src
    assert 'data-tour-step="sidebar"' in src
    assert 'sticky top-12' in src


def test_main_has_own_scroll_context() -> None:
    src = _read("base.html")
    assert 'id="hm-main"' in src
    assert 'data-tour-step="main"' in src
    assert 'overflow-y-auto h-[calc(100vh-3rem)]' in src


def test_inspector_landmark_with_collapse_toggle() -> None:
    src = _read("base.html")
    assert 'id="inspector"' in src
    assert 'data-tour-step="inspector"' in src
    # Persisted via localStorage so preference survives reloads.
    assert "hm-inspector-collapsed" in src


def test_sidebar_extracted_to_partial() -> None:
    """Sidebar lives in `_partials/_sidebar.html` so the workspace
    shell stays focused on layout. The partial must exist and base
    must include it via the `sidebar` block."""
    assert (TEMPLATE_DIR / "_partials" / "_sidebar.html").exists()
    src = _read("base.html")
    assert '{% include "_partials/_sidebar.html" %}' in src
    assert "{% block sidebar %}" in src


def test_topbar_carries_brand_and_theme_toggle() -> None:
    """KEEP: brand link + theme toggle. Auth indicator renders only
    when `auth_token` is set, so we don't assert it directly here."""
    src = _read("base.html")
    assert 'href="/"' in src
    assert "Harbormaster" in src
    assert 'themeToggle()' in src


@pytest.mark.parametrize(
    "id_attr",
    ["hm-topbar", "hm-sidebar", "hm-main", "inspector"],
)
def test_app_shell_landmarks_have_stable_ids(id_attr: str) -> None:
    """Stable ids let CSS, e2e tests, and operator scripts target
    the four shell landmarks without brittle class selectors."""
    src = _read("base.html")
    assert f'id="{id_attr}"' in src


def test_v10_legacy_landmarks_are_gone() -> None:
    """Sentinel: the v10 fixed-footer + fixed-sidebar contract is
    intentionally retired in v19. Keep them out of base.html so an
    accidental reintroduction trips this test."""
    src = _read("base.html")
    assert 'id="hm-footer"' not in src
    assert "fixed top-12 bottom-7" not in src


def test_page_templates_define_page_title_block() -> None:
    """Each top-level page contributes a centered topbar title via
    {% block page_title %}. Missing the block is a regression because
    the topbar would render an empty middle slot."""
    for name in (
        "dashboard.html",
        "project_detail.html",
        "network.html",
        "dispatcher_trace.html",
        "fan_out.html",
    ):
        src = _read(name)
        assert "{% block page_title %}" in src, f"{name} missing page_title block"

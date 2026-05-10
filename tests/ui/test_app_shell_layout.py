"""v10.0.0a3: full app-shell layout — fixed topbar + fixed sidebar
+ scrollable main content + slim fixed footer.

Pins the structural invariants of the new shell so future template
edits don't accidentally regress to the old `min-h-screen` flow
layout where the topbar scrolled away with the page.
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


def test_body_uses_fixed_height_overflow_hidden() -> None:
    """The shell relies on a height-constrained body so the inner
    main element can claim its own scroll context. The pre-v10
    `min-h-screen` (with body-level scroll) is forbidden."""
    src = _read("base.html")
    assert 'class="h-screen overflow-hidden"' in src
    # Sentinel: the old class must be gone.
    assert 'class="min-h-screen"' not in src


def test_topbar_is_fixed_with_id_and_height() -> None:
    src = _read("base.html")
    assert 'id="hm-topbar"' in src
    # Position fixed + h-12 + top-0 — the contract.
    assert "fixed top-0" in src
    assert "h-12" in src


def test_sidebar_is_fixed_below_topbar_and_above_footer() -> None:
    src = _read("base.html")
    assert 'id="hm-sidebar"' in src
    # Sidebar starts at top-12 (under the topbar) and stops at
    # bottom-7 (above the slim footer).
    assert "fixed top-12 bottom-7 left-0" in src


def test_main_is_fixed_scroll_context_offset_for_sidebar() -> None:
    src = _read("base.html")
    assert 'id="hm-main"' in src
    # Fixed between top-12 / bottom-7, full width, with overflow-y-auto.
    assert "fixed top-12 bottom-7" in src
    assert "overflow-y-auto" in src
    # Sidebar offset toggles between md:left-12 and md:left-60.
    assert "md:left-12" in src
    assert "md:left-60" in src


def test_footer_is_slim_fixed_bottom_bar() -> None:
    src = _read("base.html")
    assert 'id="hm-footer"' in src
    assert "fixed bottom-0" in src
    assert "h-7" in src


def test_topbar_nav_keeps_dashboard_fan_out_dispatcher() -> None:
    """KEEP these three nav links."""
    src = _read("base.html")
    assert 'href="/"' in src and ">Dashboard<" in src
    assert 'href="/tools/fan-out"' in src
    assert 'href="/dispatcher"' in src


def test_topbar_nav_drops_useless_api_endpoints() -> None:
    """REMOVE /api/projects + /api/health from the topbar nav.
    The endpoints still exist; they just aren't navbar links."""
    src = _read("base.html")
    # Anchor literals must be gone.
    assert ">/api/projects<" not in src
    assert ">/api/health<" not in src


@pytest.mark.parametrize(
    "id_attr",
    ["hm-topbar", "hm-sidebar", "hm-main", "hm-footer"],
)
def test_app_shell_landmarks_have_stable_ids(id_attr: str) -> None:
    """Stable ids let CSS, e2e tests, and operator scripts target
    the four shell landmarks without brittle class selectors."""
    src = _read("base.html")
    assert f'id="{id_attr}"' in src

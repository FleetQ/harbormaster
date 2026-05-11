"""v21.0.0a1: Mobile responsive drawer pattern (<1024px viewport).

Pins the structural invariants of the mobile drawer so future
template edits don't accidentally regress the topbar buttons,
drawer CSS, or appShell() state shape. Test style matches the
existing static-assertion convention in test_app_shell_layout.py —
no browser session required.
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


def _read(name: str) -> str:
    return (TEMPLATE_DIR / name).read_text()


def _button_block(src: str, aria_label: str) -> str:
    """Return the full <button…</button> markup containing the given aria-label."""
    end = src.index(aria_label)
    start = src.rfind("<button", 0, end)
    close = src.index("</button>", end) + len("</button>")
    return src[start:close]


def test_topbar_has_hamburger_button_for_sidebar() -> None:
    """Below 1024px the topbar exposes a hamburger that toggles the
    sidebar drawer. The button is `lg:hidden` so desktop never sees it."""
    src = _read("base.html")
    block = _button_block(src, 'aria-label="Toggle sidebar"')
    assert "$dispatch('hm-toggle-sidebar')" in block
    # Hamburger button must be hidden at >=1024px.
    assert "lg:hidden" in block
    # Hamburger glyph rendered.
    assert "☰" in block


def test_topbar_has_info_button_for_inspector() -> None:
    """Symmetric info ⓘ button on topbar right toggles the inspector
    drawer; also lg:hidden so desktop layout is untouched."""
    src = _read("base.html")
    block = _button_block(src, 'aria-label="Toggle inspector"')
    assert "$dispatch('hm-toggle-inspector')" in block
    assert "lg:hidden" in block
    assert "ⓘ" in block


def test_app_shell_owns_drawer_state() -> None:
    """appShell() must declare sidebarOpen + inspectorOpen so the
    topbar buttons and drawer aside elements have shared state."""
    src = _read("base.html")
    assert "sidebarOpen: false" in src
    assert "inspectorOpen: false" in src


def test_drawer_state_listens_for_dispatch_events() -> None:
    """The shell grid listens for hm-toggle-sidebar and hm-toggle-inspector
    custom events so the (decoupled) topbar buttons can drive it."""
    src = _read("base.html")
    assert "@hm-toggle-sidebar.window" in src
    assert "@hm-toggle-inspector.window" in src


def test_escape_closes_both_drawers() -> None:
    """Esc key clears both drawer states — standard a11y dismissal."""
    src = _read("base.html")
    assert "@keydown.escape.window" in src
    # Must close BOTH drawers on Escape.
    escape_handler = src.split("@keydown.escape.window")[1].split('"')[1]
    assert "sidebarOpen = false" in escape_handler
    assert "inspectorOpen = false" in escape_handler


def test_backdrop_overlay_present_and_mobile_only() -> None:
    """A clickable backdrop fades in when either drawer is open; click
    closes both. Hidden at >=1024px via lg:hidden so desktop is unaffected."""
    src = _read("base.html")
    # Find the backdrop block.
    assert "lg:hidden fixed inset-0 bg-black/50 z-30" in src
    # It must be x-show'd on either drawer being open.
    backdrop_section = src.split("bg-black/50")[0].rsplit("<div", 1)[1]
    assert "sidebarOpen || inspectorOpen" in backdrop_section


def test_sidebar_has_data_drawer_open_attribute() -> None:
    """Sidebar uses :data-drawer-open binding so the CSS @media block
    can target the open state via attribute selector. Avoids inline
    style juggling and keeps the drawer translation purely in CSS."""
    src = _read("base.html")
    assert ':data-drawer-open="sidebarOpen ? \'true\' : \'false\'"' in src


def test_inspector_has_data_drawer_open_attribute() -> None:
    src = _read("base.html")
    assert ':data-drawer-open="inspectorOpen ? \'true\' : \'false\'"' in src


def test_mobile_css_media_query_below_1024() -> None:
    """The drawer behavior is CSS-only below 1024px — fixed positioning
    + translateX off-canvas. The media query upper bound is 1023.98px
    so it doesn't fight the lg: Tailwind utilities at exactly 1024px."""
    src = _read("base.html")
    assert "@media (max-width: 1023.98px)" in src
    # Sidebar drawer CSS: fixed left, translateX(-100%)
    assert "transform: translateX(-100%)" in src
    # Inspector drawer CSS: fixed right, translateX(100%)
    assert "transform: translateX(100%)" in src
    # Open state restores translateX(0).
    assert 'data-drawer-open="true"' in src


def test_desktop_grid_layout_preserved() -> None:
    """At >=1024px the 3-column grid (240px + 1fr + inspectorWidth) must
    remain intact. v21.0.0a5 switched the inspector column from the static
    Tailwind class `grid-cols-[240px_1fr_320px]` to an inline
    `:style` binding driven by appShell()'s `inspectorWidth` state so the
    operator can drag-resize. Collapsed branch still pins 0. The drawer
    media query continues to collapse the grid only below 1024px."""
    src = _read("base.html")
    # Inline style binding drives the three-column template.
    assert "grid-template-columns: 240px 1fr ${inspectorWidth}px" in src
    assert "grid-template-columns: 240px 1fr 0" in src
    # The shell grid id is what the @media block targets.
    assert 'id="hm-shell-grid"' in src

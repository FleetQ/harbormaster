"""v21.0.0a5: Inspector drag-resize handle + keyboard shortcuts cheatsheet.

Static-template assertions pinning the structural invariants for the
two new operator-UX features. No browser session required — matches
the convention of test_v21_mobile_drawer.py.
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


# ───────────────────────── Drag-resize handle ─────────────────────────


def test_inspector_has_drag_resize_handle() -> None:
    """The inspector aside contains a vertical drag handle that fires
    startResize() on pointerdown. Desktop-only (lg:block) so the mobile
    drawer pattern is untouched."""
    src = _read("base.html")
    assert "cursor-col-resize" in src
    assert "@pointerdown=\"startResize($event)\"" in src
    # Handle is hidden in mobile drawer mode.
    assert "hidden lg:block" in src
    # ARIA semantics for a vertical resizer.
    assert 'role="separator"' in src
    assert 'aria-orientation="vertical"' in src


def test_app_shell_owns_inspector_width_state() -> None:
    """appShell() declares inspectorWidth state (default 320), seeded
    from localStorage and clamped to [240, 480]."""
    src = _read("base.html")
    # State key + default fallback.
    assert "inspectorWidth:" in src
    assert "localStorage.getItem('hm-inspector-width') || '320'" in src
    # Clamp bounds appear in the seed expression.
    assert "Math.min(480, Math.max(240," in src


def test_app_shell_has_resize_helpers() -> None:
    """appShell() exposes startResize() + applyInspectorWidth() helpers.
    startResize wires pointermove/pointerup, rAF-throttles updates, and
    persists final width on pointerup."""
    src = _read("base.html")
    assert "applyInspectorWidth()" in src
    assert "startResize(e)" in src
    # rAF throttling is required for smooth drag.
    assert "requestAnimationFrame(" in src
    # Width is persisted on pointerup.
    assert "localStorage.setItem('hm-inspector-width'," in src
    # Pointer event listeners get added + removed.
    assert "addEventListener('pointermove'" in src
    assert "addEventListener('pointerup'" in src
    assert "removeEventListener('pointermove'" in src
    assert "removeEventListener('pointerup'" in src


def test_grid_template_uses_dynamic_inspector_width() -> None:
    """The shell grid binds grid-template-columns inline via :style so
    the inspector column reflects appShell().inspectorWidth live."""
    src = _read("base.html")
    assert "grid-template-columns: 240px 1fr ${inspectorWidth}px" in src


# ───────────────────────── Cheatsheet panel ───────────────────────────


def test_cheatsheet_alpine_scope_present() -> None:
    """shortcutsCheatsheet() factory is mounted as an Alpine x-data scope
    with init() bound."""
    src = _read("base.html")
    assert "shortcutsCheatsheet()" in src
    # Factory definition exists.
    assert "function shortcutsCheatsheet()" in src


def test_cheatsheet_has_expected_groups() -> None:
    """All three documented shortcut groups appear in the data — they
    are the public contract for what the cheatsheet promises operators."""
    src = _read("base.html")
    assert "name: 'Global'" in src
    assert "name: 'Project page tabs'" in src
    assert "name: 'Memory editor'" in src


def test_cheatsheet_has_expected_global_shortcuts() -> None:
    """Global section lists the 4 promised global shortcuts."""
    src = _read("base.html")
    assert "key: '?'" in src
    assert "key: 'Esc'" in src
    assert "key: 'Cmd+K'" in src
    assert "key: 'Cmd+Shift+L'" in src


def test_cheatsheet_question_mark_opens_panel() -> None:
    """Shift+? (`e.key === '?' && e.shiftKey`) sets open=true. Input/textarea
    focus must NOT trigger the cheatsheet (avoid hijacking typed `?`)."""
    src = _read("base.html")
    assert "e.key === '?'" in src
    assert "e.shiftKey" in src
    # Ignore-when-typing guard.
    assert "INPUT" in src and "TEXTAREA" in src
    assert "isContentEditable" in src


def test_cheatsheet_cmd_shift_l_toggles_theme() -> None:
    """Cmd+Shift+L (or Ctrl+Shift+L on non-mac) toggles the theme-light
    class on <html> and persists in localStorage under hm-theme."""
    src = _read("base.html")
    # Init handler contains the theme-toggle branch.
    handler_window = src[src.index("function shortcutsCheatsheet()"):]
    assert "e.key.toLowerCase() === 'l'" in handler_window
    assert "metaKey || e.ctrlKey" in handler_window
    assert "theme-light" in handler_window
    assert "theme-dark" in handler_window
    assert "localStorage.setItem('hm-theme'," in handler_window


def test_cheatsheet_panel_has_escape_dismissal() -> None:
    """Esc closes the cheatsheet — standard a11y dismissal."""
    src = _read("base.html")
    # Find the cheatsheet block and confirm the escape handler is on it.
    chunk = src[src.index("Keyboard shortcuts cheatsheet"):]
    assert "@keydown.escape.window=\"open = false\"" in chunk


def test_cheatsheet_has_dialog_a11y_attributes() -> None:
    """Panel exposes role=dialog + aria-modal so screen readers treat it
    as a modal surface; close button is labelled."""
    src = _read("base.html")
    chunk = src[src.index("Keyboard shortcuts cheatsheet"):]
    assert 'role="dialog"' in chunk
    assert 'aria-modal="true"' in chunk
    assert 'aria-label="Keyboard shortcuts"' in chunk
    assert 'aria-label="Close cheatsheet"' in chunk

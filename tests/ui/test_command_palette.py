"""Cmd-K command palette structural audit (v8.0.0a4).

The Phase 4 deliverable is a global Alpine `commandPalette` scope
mounted in `base.html`. We audit:

* Mount point in base.html with `x-data="commandPalette()"`.
* Cmd+K / Ctrl+K trigger via `bindKeyboard()` listening for
  `metaKey || ctrlKey` + `k`.
* Categories render: Project, Tool, Page, Help.
* Bigram-based fuzzy match (`_bigrams` + `_score` helpers).
* Keyboard navigation handlers: arrow up/down, enter, escape.
* Shortcut entry in help popover ("Cmd / Ctrl + K").
* `aria-label` on the input + `role=dialog` + `aria-modal=true`.
* Lazy `/api/projects` fetch (`projectsLoaded` guard).

Static-only — same audit pattern as Phase 1/2/3 tests, no
browser fixture.
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


def test_palette_mount_in_base() -> None:
    src = _read("base.html")
    assert 'x-data="commandPalette()"' in src
    assert "x-init=\"bindKeyboard()\"" in src


def test_palette_dialog_has_aria_attrs() -> None:
    src = _read("base.html")
    assert 'role="dialog"' in src
    assert 'aria-modal="true"' in src
    assert 'aria-label="Command palette"' in src


def test_palette_input_has_aria_label() -> None:
    src = _read("base.html")
    # Input element receives the text query — must declare aria-label.
    assert 'aria-label="Search projects, tools, and shortcuts"' in src


def test_palette_listbox_semantics() -> None:
    src = _read("base.html")
    assert 'role="listbox"' in src
    assert 'role="option"' in src
    assert ":aria-selected=\"i === selectedIndex\"" in src


def test_palette_shortcut_binding() -> None:
    src = _read("base.html")
    # Cmd-K = metaKey, Ctrl-K = ctrlKey. The handler must check both.
    assert "(e.metaKey || e.ctrlKey)" in src
    assert "e.key === 'k'" in src


def test_palette_keyboard_navigation_handlers() -> None:
    src = _read("base.html")
    assert "@keydown.arrow-down.prevent=\"moveSelection(1)\"" in src
    assert "@keydown.arrow-up.prevent=\"moveSelection(-1)\"" in src
    assert "@keydown.enter.prevent=\"activate()\"" in src
    assert "@keydown.escape.window=\"if (open) close()\"" in src


def test_palette_categories_present() -> None:
    src = _read("base.html")
    # Every static catalog entry uses its category constant.
    for cat in ("Tool", "Page", "Help", "Project"):
        assert f"category: '{cat}'" in src or f"'category': '{cat}'" in src or f'"{cat}"' in src
    # Project category comes from the projects-fetch path:
    assert "category: 'Project'" in src


def test_palette_lazy_projects_fetch() -> None:
    src = _read("base.html")
    assert "projectsLoaded: false" in src
    assert "_ensureProjects()" in src
    assert "/api/projects" in src


def test_palette_fuzzy_match_helpers() -> None:
    src = _read("base.html")
    assert "_bigrams(s)" in src
    assert "_score(q, candidate)" in src
    # Exact-substring fast path must short-circuit before bigrams.
    assert "candidate.includes(q)" in src


def test_help_popover_lists_cmd_k() -> None:
    src = _read("dashboard.html")
    # The shortcut row uses `Cmd / Ctrl + K` syntax to cover both
    # platforms. Audit catches accidental drop-back to Mac-only or
    # Win-only labels.
    assert "Cmd / Ctrl + K" in src
    assert "open command palette" in src


@pytest.mark.parametrize(
    "tool_id",
    ["fan-out", "recall", "graph", "reembed", "dashboard", "shortcuts"],
)
def test_palette_static_tool_entry_present(tool_id: str) -> None:
    """Each shipped static tool entry must remain in the catalog."""
    src = _read("base.html")
    assert f"id: '{tool_id}'" in src, f"missing palette entry: {tool_id}"

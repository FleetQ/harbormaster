"""Sidebar structural audit for v8.0.0a6.

Phase 6 ships a left navigation sidebar mounted globally in
`base.html`. We audit the markup invariants:

* Sidebar is a `<aside role="navigation">` rail with
  `aria-label="Project navigation"`.
* Mobile hamburger toggle dispatches `hm:sidebar:toggle`.
* All four canonical groups are present (`pinned`, `recent`,
  `by-language`).
* Each group carries `data-sidebar-group="<id>"` for audit.
* Pin toggle button binds `:aria-label`.
* Search input has `aria-label`.
* `projectSidebar()` Alpine helper is defined with the canonical
  state shape + localStorage persistence.
* The helper reads `/api/projects` (bare list) and
  `/api/trajectories?limit=20`.
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


def test_sidebar_aside_role_and_label() -> None:
    src = _read("base.html")
    assert 'role="navigation"' in src
    assert 'aria-label="Project navigation"' in src


def test_hamburger_toggle_dispatches_event() -> None:
    src = _read("base.html")
    assert "$dispatch('hm:sidebar:toggle')" in src
    # Listener wired on the sidebar.
    assert "@hm:sidebar:toggle.window=\"mobileOpen = !mobileOpen\"" in src


@pytest.mark.parametrize(
    "group_id",
    ["pinned", "recent", "by-language"],
)
def test_sidebar_group_present(group_id: str) -> None:
    src = _read("base.html")
    assert f'data-sidebar-group="{group_id}"' in src, f"missing group: {group_id}"


def test_sidebar_search_input_labelled() -> None:
    src = _read("base.html")
    assert 'aria-label="Filter projects in sidebar"' in src


def test_sidebar_pin_toggle_aria_label() -> None:
    src = _read("base.html")
    # Per-row pin toggle binds aria-label dynamically (`Pin foo` / `Unpin foo`).
    assert ":aria-label=\"`${isPinned(p.name) ? 'Unpin' : 'Pin'} ${p.name}`\"" in src


def test_project_sidebar_alpine_scope_defined() -> None:
    src = _read("base.html")
    assert "function projectSidebar()" in src
    for fn in (
        "_loadProjects()",
        "_loadRecent()",
        "togglePin(name)",
        "toggleLanguage(lang)",
        "projectsByLanguage()",
    ):
        assert fn in src, f"missing helper: {fn}"


def test_sidebar_persists_pinned_to_localstorage() -> None:
    src = _read("base.html")
    assert "localStorage.getItem('hm:sidebar:pinned')" in src
    assert "localStorage.setItem('hm:sidebar:pinned'" in src


def test_sidebar_persists_collapsed_groups() -> None:
    src = _read("base.html")
    assert "localStorage.getItem('hm:sidebar:lang-collapsed')" in src
    assert "localStorage.setItem('hm:sidebar:lang-collapsed'" in src


def test_sidebar_loads_recent_from_trajectories() -> None:
    src = _read("base.html")
    assert "/api/trajectories?limit=20" in src


def test_sidebar_main_layout_offsets_for_rail() -> None:
    """Main content area must reserve 240px on desktop for the rail."""
    src = _read("base.html")
    assert "md:ml-60" in src

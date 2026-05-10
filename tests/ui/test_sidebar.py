"""Sidebar structural audit (updated for v19.0.0a1).

The sidebar now lives in `_partials/_sidebar.html`; base.html only
provides the `<aside id="hm-sidebar">` shell that includes it.

Invariants preserved from v8.0.0a6:
* Sidebar landmark is `<aside role="navigation">` labelled
  "Project navigation".
* All canonical groups present (`pinned`, `recent`, `by-language`).
* Each group carries `data-sidebar-group="<id>"` for audit.
* Pin toggle button binds `:aria-label`.
* Search input has `aria-label`.
* `projectSidebar()` Alpine helper is defined with the canonical
  state shape + localStorage persistence.
* Helper reads `/api/projects` and `/api/trajectories?limit=20`.

Dropped in v19.0.0a1: mobile hamburger / rail-collapse / fixed
positioning — superseded by the 3-column workspace shell.
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


def _read_sidebar() -> str:
    """Sidebar markup + script live in the partial as of v19.0.0a1."""
    return _read("_partials/_sidebar.html")


def test_sidebar_aside_role_and_label() -> None:
    """Outer landmark stays in base.html so the shell owns positioning."""
    src = _read("base.html")
    assert 'role="navigation"' in src
    assert 'aria-label="Project navigation"' in src


@pytest.mark.parametrize(
    "group_id",
    ["pinned", "recent", "by-language"],
)
def test_sidebar_group_present(group_id: str) -> None:
    src = _read_sidebar()
    assert f'data-sidebar-group="{group_id}"' in src, f"missing group: {group_id}"


def test_sidebar_search_input_labelled() -> None:
    src = _read_sidebar()
    assert 'aria-label="Filter projects in sidebar"' in src


def test_sidebar_pin_toggle_aria_label() -> None:
    src = _read_sidebar()
    # Per-row pin toggle binds aria-label dynamically (`Pin foo` / `Unpin foo`).
    assert ":aria-label=\"`${isPinned(p.name) ? 'Unpin' : 'Pin'} ${p.name}`\"" in src


def test_project_sidebar_alpine_scope_defined() -> None:
    src = _read_sidebar()
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
    src = _read_sidebar()
    assert "localStorage.getItem('hm:sidebar:pinned')" in src
    assert "localStorage.setItem('hm:sidebar:pinned'" in src


def test_sidebar_persists_collapsed_groups() -> None:
    src = _read_sidebar()
    assert "localStorage.getItem('hm:sidebar:lang-collapsed')" in src
    assert "localStorage.setItem('hm:sidebar:lang-collapsed'" in src


def test_sidebar_loads_recent_from_trajectories() -> None:
    src = _read_sidebar()
    assert "/api/trajectories?limit=20" in src

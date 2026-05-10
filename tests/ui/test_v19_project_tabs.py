"""v19.0.0a2: tab system on project_detail.html.

Pins the structural invariants of the 5-tab layout (Overview, Memories,
Trajectories, Q&A History, Settings) and the projectTabs() Alpine
controller so future template edits don't accidentally break the tab
strip, the URL-hash persistence, or the keyboard-shortcut bindings.

Mirrors the test_app_shell_layout.py pattern — pure template-source
assertions, no live server. Behavioural integration (hash mutates on
click; 1-5 keys cycle tabs; trajectoryList still receives events) is
covered by browser smoke runs against /projects/<name>.
"""
from __future__ import annotations

from pathlib import Path

import pytest

TEMPLATE_PATH = (
    Path(__file__).parent.parent.parent
    / "src"
    / "harbormaster"
    / "ui"
    / "templates"
    / "project_detail.html"
)


def _read() -> str:
    return TEMPLATE_PATH.read_text()


def test_tab_strip_renders_with_five_tabs() -> None:
    """The Alpine factory must register exactly the 5 tabs the spec
    promises, in the documented order — operator muscle-memory for
    keyboard shortcuts (1=overview … 5=settings) depends on it."""
    src = _read()
    # Factory tab list (order matters — keyboard shortcut indices map
    # 1..5 to this array).
    for i, tab_id in enumerate(
        ["overview", "memories", "trajectories", "qa-history", "settings"], start=1
    ):
        assert f"id: '{tab_id}'" in src, f"tab {tab_id!r} missing from factory"
        assert f"shortcut: '{i}'" in src, f"shortcut {i} missing"
    # Tab strip is wrapped in a nav with a stable id so e2e tests + CSS
    # can target it without brittle class selectors.
    assert 'id="hm-project-tabs"' in src


def test_each_tab_has_a_panel_with_role_tabpanel() -> None:
    """Every tab id needs a matching <section role='tabpanel'> guarded
    by `x-show="active === '<id>'"` — otherwise switching tabs would
    leave a blank pane."""
    src = _read()
    for tab_id in (
        "overview",
        "memories",
        "trajectories",
        "qa-history",
        "settings",
    ):
        assert (
            f"x-show=\"active === '{tab_id}'\"" in src
        ), f"tab panel for {tab_id!r} missing x-show guard"
    # Five panels, all with role="tabpanel".
    assert src.count('role="tabpanel"') == 5


def test_url_hash_drives_active_tab() -> None:
    """`restoreFromHash` reads `#tab=<id>` on init and `setTab` writes
    it back on click — together they make the active tab survive
    reloads and shareable via URL."""
    src = _read()
    assert "restoreFromHash()" in src
    assert "window.location.hash.match" in src
    # Strict regex anchors prevent accidental matches like #tab=foo&bar.
    assert "/^#tab=([\\w-]+)$/" in src
    # setTab must replaceState (not pushState) so back-button stays
    # bound to navigation, not tab toggling.
    assert "window.history.replaceState(null, '', '#tab=' + id)" in src


def test_keyboard_shortcuts_skip_inputs_and_modifiers() -> None:
    """1..5 keys cycle tabs but MUST be ignored when the user is
    typing in an INPUT/TEXTAREA/contentEditable, or when modifier
    keys are held — those gestures belong to the command palette
    (Cmd+K) and the browser (Cmd+1 = first tab)."""
    src = _read()
    assert "['INPUT', 'TEXTAREA'].includes(e.target.tagName)" in src
    assert "isContentEditable" in src
    assert "e.metaKey || e.ctrlKey || e.altKey" in src
    assert "/^[1-5]$/.test(e.key)" in src


def test_trajectories_tab_contains_trajectory_list_component() -> None:
    """The pre-v19 standalone trajectoryList component must live INSIDE
    the Trajectories tab panel now (relocated, not duplicated). We
    assert (a) the trajectoryList factory call appears, (b) it appears
    after the Trajectories tab opener, and (c) the original standalone
    location no longer exists outside the tab system."""
    src = _read()
    traj_open_idx = src.find("x-show=\"active === 'trajectories'\"")
    traj_factory_idx = src.find('x-data="trajectoryList({')
    assert traj_open_idx >= 0, "Trajectories tab panel missing"
    assert traj_factory_idx >= 0, "trajectoryList component missing"
    assert traj_factory_idx > traj_open_idx, (
        "trajectoryList must render inside the Trajectories tab panel"
    )
    # And there must be only one trajectoryList — no accidental duplicate.
    assert src.count('x-data="trajectoryList({') == 1


def test_overview_tab_keeps_existing_header_status_and_forms() -> None:
    """The Overview tab is the existing project header + status block
    + ask/delegate forms — don't lose them in the relocate."""
    src = _read()
    overview_idx = src.find("x-show=\"active === 'overview'\"")
    memories_idx = src.find("x-show=\"active === 'memories'\"")
    assert overview_idx >= 0
    assert memories_idx > overview_idx
    overview_block = src[overview_idx:memories_idx]
    assert '{{ project_name }}' in overview_block
    assert '{{ status_markdown }}' in overview_block
    assert '{% include "_partials/ask_form.html" %}' in overview_block
    assert '{% include "_partials/delegate_form.html" %}' in overview_block


@pytest.mark.parametrize(
    "tab_id,marker",
    [
        ("memories", "lands in v19.0.0a6"),
        ("qa-history", "v19.0.0a5"),
    ],
)
def test_placeholder_tabs_signal_target_version(tab_id: str, marker: str) -> None:
    """Memories and Q&A History tabs ship as placeholders in a2; the
    operator needs to see the target alpha for the full impl so they
    don't file regressions when those tabs look bare."""
    src = _read()
    panel_open = src.find(f"x-show=\"active === '{tab_id}'\"")
    assert panel_open >= 0
    # Look forward to the next </section> to bound the panel content.
    panel_close = src.find("</section>", panel_open)
    assert panel_close > panel_open
    panel = src[panel_open:panel_close]
    assert marker in panel, f"{tab_id} tab missing version marker {marker!r}"


def test_settings_tab_renders_read_only_metadata_grid() -> None:
    """Settings tab is populated with read-only metadata in a2 (path,
    last commit, language, budget). a4 will add per-project budget
    edit; the dl grid is the placeholder shape for that."""
    src = _read()
    settings_idx = src.find("x-show=\"active === 'settings'\"")
    assert settings_idx >= 0
    settings_block = src[settings_idx:]
    # Metadata fields the spec requires.
    for field in (
        "Project name",
        "Path",
        "Last commit",
        "Language",
        "Daily call budget",
    ):
        assert field in settings_block, f"settings tab missing {field!r} field"
    # `<dl>` shape lets a4's edit controls slot in without restructuring.
    assert "<dl" in settings_block

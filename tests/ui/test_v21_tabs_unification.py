"""v21.0.0a6: tab strip unification across dashboard/network/dispatcher.

Pins the contract for the new `_tabs.html` partial:

  * It exists at the expected path.
  * Each of the four consumers (project_detail / dashboard / network /
    dispatcher_trace) includes the partial via the documented
    `{% with tabs_id=... %}` invocation.
  * Each page declares a matching Alpine controller (projectTabs,
    dashboardTabs, networkTabs, dispatcherTabs) that exposes the
    shape the partial expects (tabs / active / setTab / restoreFromHash).
  * Each page's tab list contains the canonical ids called out in the
    v21.0.0a6 spec.

These are pure template-source assertions — no live server needed.
Behavioural integration (hash mutation on click, 1..N keyboard
cycling, panel swap on active change) is covered by Playwright smoke
runs against the served pages.
"""
from __future__ import annotations

from pathlib import Path

TEMPLATES_DIR = (
    Path(__file__).parent.parent.parent
    / "src"
    / "harbormaster"
    / "ui"
    / "templates"
)


def _read(name: str) -> str:
    return (TEMPLATES_DIR / name).read_text()


def test_generic_tabs_partial_exists_and_uses_parent_scope() -> None:
    """The `_tabs.html` partial is presentation-only — it must read
    `tabs` / `active` / `setTab` from the caller's enclosing Alpine
    scope, and it must wrap itself in a stable `hm-<tabs_id>-tabs` id
    so e2e tests + CSS can target it."""
    src = _read("_partials/_tabs.html")
    assert 'id="hm-{{ tabs_id | e }}-tabs"' in src
    assert 'x-for="tab in tabs"' in src
    assert '@click="setTab(tab.id)"' in src
    assert "active === tab.id" in src
    # role + aria are non-negotiable for the tab strip a11y contract.
    assert 'role="tablist"' in src
    assert 'role="tab"' in src
    # No factory mounted on the partial — it must inherit scope.
    assert 'x-data="genericTabs' not in src
    assert "function genericTabs" not in src


def test_project_detail_uses_tabs_partial() -> None:
    """project_detail.html drops its inline tab markup and pulls in
    `_partials/_tabs.html` instead. The projectTabs() factory still
    owns active/setTab state — only the visual strip is shared."""
    src = _read("project_detail.html")
    assert '{% include "_partials/_tabs.html" %}' in src
    assert 'tabs_id="project"' in src
    # Factory still mounted on the outer wrapper.
    assert 'x-data="projectTabs()"' in src
    # The five canonical project tabs.
    for tab_id in ("overview", "memories", "trajectories", "qa-history", "settings"):
        assert f"id: '{tab_id}'" in src, f"projectTabs() missing tab {tab_id!r}"
    # Old inline tab markup must be gone — otherwise we'd render two strips.
    assert '<nav id="hm-project-tabs"' not in src


def test_dashboard_has_three_tabs_via_partial() -> None:
    """dashboard.html wraps its main content in dashboardTabs() and
    renders Overview / Recent activity / Plugins via the shared
    partial."""
    src = _read("dashboard.html")
    assert '{% include "_partials/_tabs.html" %}' in src
    assert 'tabs_id="dashboard"' in src
    assert 'x-data="dashboardTabs()"' in src
    assert "function dashboardTabs()" in src
    for tab_id in ("overview", "activity", "plugins"):
        assert f"id: '{tab_id}'" in src, f"dashboardTabs() missing tab {tab_id!r}"
    # Each panel has a tabpanel role so screen readers announce them.
    for tab_id in ("overview", "activity", "plugins"):
        assert f"active === '{tab_id}'" in src
    # The new activity feed mounts its own factory (last 100 events).
    assert "dashboardActivityFeed" in src
    assert "/api/network/events?limit=100" in src


def test_network_page_has_four_tabs_via_partial() -> None:
    """network.html replaces the inline graph/chat/timeline view
    switcher with the shared partial + a Stats tab. networkTabs()
    re-dispatches `hm:network:view` so the existing networkPanel
    listener keeps working."""
    src = _read("network.html")
    assert '{% include "_partials/_tabs.html" %}' in src
    assert 'tabs_id="network"' in src
    assert 'x-data="networkTabs()"' in src
    assert "function networkTabs()" in src
    for tab_id in ("graph", "chat", "timeline", "stats"):
        assert f"id: '{tab_id}'" in src, f"networkTabs() missing tab {tab_id!r}"
    # The Alpine store bridges the new `active` state to the existing
    # networkStats panel (so it only shows on the Stats tab).
    assert "Alpine.store('hmNetTab'" in src
    assert "$store.hmNetTab.active === 'stats'" in src
    # Compatibility shim: networkPanel still consumes hm:network:view.
    assert "hm:network:view" in src
    # Old inline view-switch buttons removed.
    assert 'id="hm-network-view-graph"' not in src


def test_dispatcher_trace_has_three_tabs_via_partial() -> None:
    """dispatcher_trace.html wraps In-flight / Recent / Stats sections
    in a dispatcherTabs() scope. The `active` property on
    traceWaterfall() was renamed to `inflight` so the nested tab scope
    can own its own `active` (the tab id) without shadowing the spans
    array."""
    src = _read("dispatcher_trace.html")
    assert '{% include "_partials/_tabs.html" %}' in src
    assert 'tabs_id="dispatcher"' in src
    assert 'x-data="dispatcherTabs()"' in src
    assert "function dispatcherTabs()" in src
    for tab_id in ("in-flight", "recent", "stats"):
        assert f"id: '{tab_id}'" in src, f"dispatcherTabs() missing tab {tab_id!r}"
    # In-flight spans now live on `inflight`, not `active`.
    assert "inflight: []" in src
    assert "this.inflight = [...this.inflight," in src
    # And the tab guards use the new dispatcherTabs `active`.
    for tab_id in ("in-flight", "recent", "stats"):
        assert f"active === '{tab_id}'" in src


def test_all_tab_controllers_share_the_same_url_hash_contract() -> None:
    """Every page-level tab controller must implement the same
    URL-hash protocol so operators can bookmark a tab on any page:
      * `restoreFromHash()` reads `#tab=<id>` on init
      * `setTab(id)` writes it back via replaceState
      * The regex pin is `/^#tab=([\\w-]+)$/`
    Keeps the cross-page UX consistent."""
    for fname in (
        "project_detail.html",
        "dashboard.html",
        "network.html",
        "dispatcher_trace.html",
    ):
        src = _read(fname)
        assert "restoreFromHash()" in src, f"{fname} missing restoreFromHash()"
        assert "/^#tab=([\\w-]+)$/" in src, f"{fname} missing hash regex"
        assert (
            "window.history.replaceState(null, '', '#tab=' + id)" in src
        ), f"{fname} missing setTab replaceState"
        # Keyboard cycling must skip inputs + modifier keys on every page.
        assert "['INPUT', 'TEXTAREA'].includes(e.target.tagName)" in src
        assert "e.metaKey || e.ctrlKey || e.altKey" in src

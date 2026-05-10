"""v9.0.0a6: sidebar polish + palette dynamic-action.

Three v8-deferred items consolidated into one phase:

* Sidebar Archived group (last_commit_age_days >= 90).
* Sidebar rail-collapse with localStorage persistence.
* Sidebar per-host filter dropdown.
* Palette dynamic-action: typing `Ask <project> <question>` composes
  a navigate-to-project-with-prefilled-question action without
  leaving the palette.

The `stateBadge(state)` helper unification listed in the v9 plan is
deferred to v10 — pure refactoring with no observable user value,
documented in the v9.0.0a6 retro.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from harbormaster.projects import _commit_age_days

REPO_ROOT = Path(__file__).parent.parent.parent
BASE_HTML = REPO_ROOT / "src" / "harbormaster" / "ui" / "templates" / "base.html"


# -- ProjectInfo.last_commit_age_days ------------------------------------


def test_commit_age_days_today() -> None:
    iso = datetime.now(tz=UTC).isoformat()
    assert _commit_age_days({"hash": "abc", "subject": "x", "date": iso}) == 0


def test_commit_age_days_one_year_ago() -> None:
    one_year = datetime.now(tz=UTC) - timedelta(days=365)
    iso = one_year.isoformat()
    age = _commit_age_days({"hash": "abc", "subject": "x", "date": iso})
    assert age is not None
    assert 363 <= age <= 366  # tolerate leap years + clock skew


def test_commit_age_days_none_when_last_commit_missing() -> None:
    assert _commit_age_days(None) is None


def test_commit_age_days_handles_malformed_date() -> None:
    assert _commit_age_days({"hash": "x", "subject": "y", "date": "garbage"}) is None
    assert _commit_age_days({}) is None


def test_commit_age_days_handles_naive_datetime() -> None:
    """Edge case: ISO string without timezone. Treat as UTC."""
    iso = (datetime.now() - timedelta(days=100)).isoformat()
    age = _commit_age_days({"hash": "x", "subject": "y", "date": iso})
    assert age is not None
    assert 99 <= age <= 101


# -- Sidebar template assertions ----------------------------------------


def test_archived_section_present_in_template() -> None:
    src = BASE_HTML.read_text()
    assert 'data-sidebar-group="archived"' in src
    assert "visibleArchived()" in src
    assert "_isArchived" in src


def test_archived_threshold_pinned_at_90() -> None:
    """The 90-day threshold is the v9 spec; pin it so future tweaks
    surface in code review."""
    src = BASE_HTML.read_text()
    assert ">= 90" in src, (
        "archived threshold (90 days) must remain explicit in the "
        "template script — operators referencing the spec depend on it"
    )


def test_rail_collapse_state_present() -> None:
    src = BASE_HTML.read_text()
    assert "railCollapsed" in src
    assert "toggleRail()" in src
    assert "expandRail()" in src
    assert "hm:sidebar:rail-collapsed" in src  # localStorage key


def test_rail_collapsed_offset_main_content() -> None:
    """When the rail is collapsed the main content's left margin
    must shrink from 60 to 12 (Tailwind units = 240px → 48px)."""
    src = BASE_HTML.read_text()
    # Main content has both classes bound conditionally on railCollapsed.
    assert "railCollapsed ? 'md:ml-12' : 'md:ml-60'" in src


def test_host_filter_dropdown_present() -> None:
    src = BASE_HTML.read_text()
    assert 'x-model="hostFilter"' in src
    assert "availableHosts" in src
    assert "hm:sidebar:host-filter" in src  # localStorage key


def test_host_filter_default_all_hosts() -> None:
    """`__all__` is the canonical no-filter sentinel; the dropdown
    default must be that."""
    src = BASE_HTML.read_text()
    assert "hostFilter: '__all__'" in src
    assert "all hosts" in src  # display label


# -- Palette dynamic-action ---------------------------------------------


def test_palette_dynamic_action_pattern_present() -> None:
    src = BASE_HTML.read_text()
    # The regex match for `Ask <project> <question>`.
    assert "/^ask\\s+" in src or "rawQuery.match" in src
    assert "dynamic-action" in src
    assert "↵ to dispatch" in src


def test_palette_dynamic_action_navigates_with_prefilled_query() -> None:
    """The action must build a URL with `?q=<question>` so the project
    page can pre-populate the ask form."""
    src = BASE_HTML.read_text()
    assert "?q=' + encodeURIComponent(question)" in src
    assert "/projects/' + encodeURIComponent(project.id)" in src


# -- ProjectInfo serialization includes the new field --------------------


def test_project_info_as_dict_includes_age() -> None:
    """v9.0.0a6: as_dict must surface `last_commit_age_days` so the
    sidebar's `_isArchived` check has the field to read."""
    from harbormaster.projects import ProjectInfo

    info = ProjectInfo(
        name="demo", path="/tmp/demo",
        last_commit={"hash": "abc", "subject": "x", "date": "2026-01-01T00:00:00+00:00"},
        has_serena=False, has_claude_md=False, brief="",
        language="python", last_commit_age_days=42,
    )
    d = info.as_dict()
    assert "last_commit_age_days" in d
    assert d["last_commit_age_days"] == 42


def test_project_info_default_age_is_none() -> None:
    from harbormaster.projects import ProjectInfo

    info = ProjectInfo(
        name="x", path="/tmp/x",
        last_commit=None,
        has_serena=False, has_claude_md=False, brief="",
    )
    assert info.last_commit_age_days is None

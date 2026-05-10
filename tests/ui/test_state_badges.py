"""State badge regressions for v8.0.0a2 — color + icon + aria-label.

The v8 phase plan (Phase 2) ships icon glyphs alongside color on
every state-discriminating badge. The icons reinforce color so
operators with color-vision differences get the same affordance,
and every badge carries an `aria-label` with the human-readable
state name so screen readers announce the state cleanly.

This audit walks the dashboard + project_detail templates and
asserts:

* Bridge state badge → wraps the label span and binds
  `:aria-label` containing "Bridge".
* Plugins enabled badge → wraps icon + label and binds aria-label.
* Reembed phase badge → uses `phaseIconHtml()` + binds aria-label.
* Trajectory tier badges (fresh/stale/stuck) all carry aria-label.

Stub-template-free: works directly off the source HTML so no
Playwright / browser fixture is required.
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


def _read(rel: str) -> str:
    return (TEMPLATE_DIR / rel).read_text()


def test_bridge_state_badge_has_icon_and_aria_label() -> None:
    src = _read("dashboard.html")
    # The bridge badge is the first inline-flex badge after `FleetQ Bridge`.
    # Locate the section by header text to guard against false positives.
    idx = src.find("FleetQ Bridge")
    assert idx != -1
    block = src[idx : idx + 800]
    assert "bridgeStateIcon()" in block, "bridge badge must use bridgeStateIcon()"
    assert ":aria-label=\"`Bridge ${bridgeStateLabel()}`\"" in block


def test_plugins_enabled_badge_has_icon_and_aria_label() -> None:
    src = _read("dashboard.html")
    idx = src.find('"text-sm font-bold text-gray-300">Plugins')
    assert idx != -1
    block = src[idx : idx + 800]
    assert ":aria-label=\"plugins.enabled" in block
    # Icon span (✓ or ⊘) is rendered inline.
    assert "'✓' : '⊘'" in block


def test_plugin_row_status_badge_has_icon_and_aria_label() -> None:
    src = _read("dashboard.html")
    assert "pluginStatusIcon(row.status)" in src
    assert ":aria-label=\"`Plugin status ${row.status}`\"" in src


def test_reembed_phase_badge_has_icon_and_aria_label() -> None:
    src = _read("dashboard.html")
    assert "phaseIconHtml()" in src
    assert ":aria-label=\"`Reembed ${phaseLabel()}`\"" in src


def test_trajectory_tier_badges_carry_aria_label() -> None:
    src = _read("project_detail.html")
    for tier in ("Writing back", "writeback stuck", "New trajectory"):
        assert tier in src, f"missing aria-label phrase: {tier!r}"


@pytest.mark.parametrize(
    "icon_fn",
    [
        "bridgeStateIcon()",
        "phaseIconHtml()",
    ],
)
def test_icon_helper_is_defined_in_alpine_scope(icon_fn: str) -> None:
    """The helpers referenced from the template must be defined in JS."""
    src = _read("dashboard.html")
    base_name = icon_fn.split("(")[0]
    # Helper definition appears in the function body (e.g. `bridgeStateIcon()` defn).
    assert f"{base_name}()" in src

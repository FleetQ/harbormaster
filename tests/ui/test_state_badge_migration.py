"""v12.0.0a2: complete stateBadge migration.

v11.0.0a4 introduced the shared `_state_badge.html` helper but only
migrated the network status pill — statusStrip + reembedPanel +
trajectoryList still rendered their own inline icon+label spans.

This test file verifies that:

  - statusStrip's bridge + plugins badges + per-row plugin status
    badges now consume `window.harbormaster.stateBadgeHtml(...)` via
    `bridgeBadgeProps()` / `pluginsBadgeProps()` / `pluginRowBadgeProps()`.
  - reembedPanel's phase badge now consumes the helper via
    `phaseBadgeProps()`.
  - trajectoryList's `fresh` and `stuck` tier badges now consume the
    helper via `tierBadgeProps()`. The `stale` tier remains a
    pure-spinner element (intentionally label-less per v6.0.0a2
    design — bare span keeps screen-reader semantics correct).
  - The helper now accepts an optional `title` (tooltip) and an
    `iconHtml` flag (for the spinner phase badge).

These are structural checks — they assert the migration markers are
in the rendered HTML and the legacy inline `:class="bridgeBadgeClass()"`
patterns are gone. Visual identity is preserved by the helper itself
(covered by `test_state_badge_and_prefill.py` color-allowlist tests)
plus the new `iconHtml` / `title` / `ariaLabel` assertions below.
"""
from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from harbormaster.config import HarbormasterConfig, ProjectsConfig
from harbormaster.ui import create_app


def _make_project_dir(parent: Path, name: str) -> Path:
    p = parent / name
    p.mkdir(parents=True)
    (p / ".git").mkdir()
    return p


def _config(tmp_path: Path) -> HarbormasterConfig:
    return HarbormasterConfig(
        projects=ProjectsConfig(glob=[f"{tmp_path}/*"]),
    )


# -- helper supports new props ----------------------------------------


def _badge_partial_text() -> str:
    src_path = (
        Path(__file__).parent.parent.parent
        / "src" / "harbormaster" / "ui"
        / "templates" / "_partials" / "_state_badge.html"
    )
    return src_path.read_text(encoding="utf-8")


def test_state_badge_helper_now_accepts_title_prop() -> None:
    """v12.0.0a2: optional tooltip via `title` prop. Required for
    statusStrip's heartbeat-age tooltip to round-trip through the
    helper."""
    text = _badge_partial_text()
    assert "props.title" in text
    assert "title=\"' + escapeHtml(title)" in text


def test_state_badge_helper_now_accepts_icon_html_flag() -> None:
    """v12.0.0a2: opt-in raw-HTML icon (NOT escaped). Required for
    reembedPanel's animated spinner phase icon."""
    text = _badge_partial_text()
    assert "props.iconHtml" in text
    assert "iconHtml ? icon : escapeHtml(icon)" in text


def test_state_badge_helper_now_accepts_aria_label_override() -> None:
    """v12.0.0a2: optional `ariaLabel` prop overrides the default
    (which is `label`). Used so the bridge badge's visible text reads
    'connected' but the aria-label says 'Bridge connected'."""
    text = _badge_partial_text()
    assert "props.ariaLabel" in text


# -- statusStrip migration --------------------------------------------


def test_statusstrip_bridge_uses_shared_helper(tmp_path: Path) -> None:
    client = TestClient(create_app(_config(tmp_path)))
    body = client.get("/").text
    # New form: helper invocation via bridgeBadgeProps.
    assert "stateBadgeHtml(bridgeBadgeProps())" in body
    # Old form gone: no inline span with bridgeBadgeClass binding.
    assert ':class="bridgeBadgeClass()"' not in body


def test_statusstrip_plugins_uses_shared_helper(tmp_path: Path) -> None:
    client = TestClient(create_app(_config(tmp_path)))
    body = client.get("/").text
    assert "stateBadgeHtml(pluginsBadgeProps())" in body
    # Old per-condition class map removed for the plugins enabled badge.
    assert "plugins.enabled ? 'bg-emerald-900/50" not in body


def test_statusstrip_plugin_row_uses_shared_helper(tmp_path: Path) -> None:
    client = TestClient(create_app(_config(tmp_path)))
    body = client.get("/").text
    assert "stateBadgeHtml(pluginRowBadgeProps(row))" in body
    # Old per-row class map gone.
    assert "'bg-emerald-900/50 text-emerald-300': row.status === 'loaded'" not in body


def test_bridge_badge_color_helper_present(tmp_path: Path) -> None:
    """The new color-name selector for the bridge badge is what the
    shared helper expects (a color *name*, not Tailwind classes)."""
    client = TestClient(create_app(_config(tmp_path)))
    body = client.get("/").text
    assert "bridgeBadgeColor()" in body
    # Color names match the helper's COLOR_CLASSES allowlist.
    for name in ("'emerald'", "'amber'", "'rose'", "'cyan'", "'gray'"):
        assert name in body


def test_plugin_row_badge_color_helper_present(tmp_path: Path) -> None:
    client = TestClient(create_app(_config(tmp_path)))
    body = client.get("/").text
    assert "pluginRowBadgeColor(status)" in body


# -- reembedPanel migration -------------------------------------------


def test_reembed_phase_uses_shared_helper(tmp_path: Path) -> None:
    client = TestClient(create_app(_config(tmp_path)))
    body = client.get("/").text
    assert "stateBadgeHtml(phaseBadgeProps())" in body
    # Old form gone: no inline span with phaseBadgeClass binding.
    assert ':class="phaseBadgeClass()"' not in body


def test_phase_badge_props_passes_icon_html_flag(tmp_path: Path) -> None:
    """The `running` phase icon is a spinner span (raw HTML); other
    phases are glyphs. phaseBadgeProps() must set iconHtml=true only
    when the spinner is in play."""
    client = TestClient(create_app(_config(tmp_path)))
    body = client.get("/").text
    assert "phaseBadgeProps()" in body
    assert "iconHtml: isRunning" in body


def test_phase_badge_color_helper_present(tmp_path: Path) -> None:
    client = TestClient(create_app(_config(tmp_path)))
    body = client.get("/").text
    assert "phaseBadgeColor()" in body


# -- trajectoryList migration -----------------------------------------


def test_trajectory_fresh_and_stuck_use_shared_helper(tmp_path: Path) -> None:
    p = _make_project_dir(tmp_path, "alpha")
    (p / "CLAUDE.md").write_text("x", encoding="utf-8")
    client = TestClient(create_app(_config(tmp_path)))
    body = client.get("/projects/alpha").text
    assert "stateBadgeHtml(tierBadgeProps('stuck'))" in body
    assert "stateBadgeHtml(tierBadgeProps('fresh'))" in body
    # Old hard-coded inline pills gone for fresh/stuck.
    assert 'class="text-cyan-400 font-bold"><span aria-hidden="true">●</span>&nbsp;new' not in body
    assert 'class="text-rose-400 font-bold"' not in body


def test_trajectory_stale_remains_bare_spinner(tmp_path: Path) -> None:
    """v6.0.0a2 design: the `stale` tier is intentionally label-less
    (a pure animated spinner). Migration MUST NOT route it through
    the helper because that would add a visible label."""
    p = _make_project_dir(tmp_path, "alpha")
    (p / "CLAUDE.md").write_text("x", encoding="utf-8")
    client = TestClient(create_app(_config(tmp_path)))
    body = client.get("/projects/alpha").text
    # Spinner element preserved (border-amber-400 + animate-spin + role=status).
    assert 'role="status"' in body
    assert 'animate-spin' in body
    assert 'aria-label="Writing back to FleetQ"' in body
    # And it does NOT call the helper for the stale tier.
    assert "stateBadgeHtml(tierBadgeProps('stale'))" not in body


def test_tier_badge_props_returns_v6_canonical_strings(tmp_path: Path) -> None:
    """The visible label and color for fresh/stuck in tierBadgeProps
    match the pre-migration text exactly — no UX regression."""
    p = _make_project_dir(tmp_path, "alpha")
    (p / "CLAUDE.md").write_text("x", encoding="utf-8")
    client = TestClient(create_app(_config(tmp_path)))
    body = client.get("/projects/alpha").text
    assert "label: 'new'" in body
    assert "label: 'stuck?'" in body
    assert "color: 'cyan'" in body  # fresh color preserved
    assert "color: 'rose'" in body  # stuck color preserved
    assert "ariaLabel: 'New trajectory'" in body
    assert "ariaLabel: 'Trajectory writeback stuck'" in body


# -- closure: deviation from v11.0.0a4 retro is now closed ------------


def test_v11a4_deviation_closed(tmp_path: Path) -> None:
    """The v11.0.0a4 retro recorded `migrate-status-pills-to-unified-
    badge` as a v12 candidate. v12.0.0a2 closes it: every badge surface
    listed in that retro now routes through `stateBadgeHtml`."""
    client = TestClient(create_app(_config(tmp_path)))
    dashboard = client.get("/").text
    # Three migrated invocations on the dashboard:
    helper_calls = dashboard.count("window.harbormaster.stateBadgeHtml(")
    assert helper_calls >= 4  # bridge + plugins + plugin row + reembed phase

"""v12.0.0a7: light-mode toggle.

The dashboard's CSS theme is built from OKLCH tokens defined in
`tailwind.input.css` (and the inline `:root` fallback in `base.html`).
v12.0.0a7 introduces a parallel light-mode token set + a manual
toggle that cycles auto → light → dark → auto, persisted to
localStorage.

Activation rules:
  - Default `auto`: `@media (prefers-color-scheme: light)` overrides
    the @theme defaults. No class on <html>.
  - Explicit `light`: class `theme-light` on <html> (wins over the
    media query).
  - Explicit `dark`: class `theme-dark` on <html> (wins even when
    system prefers light).

This test file covers:
  - The CSS source contains the new tokens for both activation paths.
  - The built `tailwind.css` artefact also carries the new tokens
    (smoke that the build hook output is in sync).
  - The toggle button + `themeToggle()` factory render in HTML.
  - The early IIFE applies the persisted class BEFORE Alpine boots
    (no FOUC).
  - Cycle order (auto → light → dark → auto) is hard-pinned so
    operators can rely on a stable affordance.
"""
from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from harbormaster.config import HarbormasterConfig, ProjectsConfig
from harbormaster.ui import create_app

_STATIC_CSS = (
    Path(__file__).parent.parent.parent
    / "src" / "harbormaster" / "ui" / "static"
)


def _read(name: str) -> str:
    return (_STATIC_CSS / name).read_text(encoding="utf-8")


def _config(tmp_path: Path) -> HarbormasterConfig:
    return HarbormasterConfig(
        projects=ProjectsConfig(glob=[f"{tmp_path}/*"]),
    )


# -- CSS tokens ------------------------------------------------------


def test_input_css_defines_light_mode_media_query() -> None:
    text = _read("tailwind.input.css")
    assert "@media (prefers-color-scheme: light)" in text


def test_input_css_defines_theme_light_class() -> None:
    text = _read("tailwind.input.css")
    assert "html.theme-light" in text
    # v19.0.0a4: light surface uses the violet-tinted high-lightness
    # value (was the chroma-zero `oklch(0.98 0 0)` in v12.0.0a7).
    assert "--color-surface-1: oklch(0.97 0.005 280)" in text


def test_input_css_defines_theme_dark_explicit_override() -> None:
    """`html.theme-dark` is needed so an operator on a light system
    can opt-in to dark mode (otherwise `auto` would always pick
    light from the media query)."""
    text = _read("tailwind.input.css")
    assert "html.theme-dark" in text
    # v19.0.0a4: dark surface dropped from 0.20 → 0.15 (true near-
    # black) and gained a faint cool tint (chroma 0.005, hue 280).
    assert "--color-surface-1: oklch(0.15 0.005 280)" in text


def test_built_tailwind_css_has_light_mode_tokens() -> None:
    """The built artefact must carry the new tokens — guard against
    a stale build slipping into the wheel."""
    text = _read("tailwind.css")
    assert "theme-light" in text
    assert "prefers-color-scheme:light" in text or "prefers-color-scheme: light" in text


# -- HTML toggle wiring ---------------------------------------------


def test_toggle_button_renders_in_topbar(tmp_path: Path) -> None:
    client = TestClient(create_app(_config(tmp_path)))
    body = client.get("/").text
    assert 'x-data="themeToggle()"' in body
    assert "@click=\"cycle()\"" in body
    # icon() returns sun/moon/half glyphs.
    assert "x-text=\"icon()\"" in body


def test_themetoggle_factory_defined_globally(tmp_path: Path) -> None:
    """The factory is declared on `window` so x-data="themeToggle()"
    resolves on first paint — Alpine doesn't have to wait for a
    separate `Alpine.data` registration."""
    client = TestClient(create_app(_config(tmp_path)))
    body = client.get("/").text
    assert "window.themeToggle = function themeToggle()" in body


def test_early_iife_applies_persisted_theme(tmp_path: Path) -> None:
    """The pre-Alpine IIFE reads localStorage and applies the class
    BEFORE first paint to avoid FOUC."""
    client = TestClient(create_app(_config(tmp_path)))
    body = client.get("/").text
    assert "function applyTheme()" in body
    assert "localStorage.getItem('hm-theme')" in body
    assert "classList.add('theme-light')" in body
    assert "classList.add('theme-dark')" in body


def test_cycle_order_is_auto_light_dark(tmp_path: Path) -> None:
    """The cycle: auto → light → dark → auto. Pinned in JS source so
    operators can rely on it. The factory exposes a single `cycle()`
    method to keep the affordance stable."""
    client = TestClient(create_app(_config(tmp_path)))
    body = client.get("/").text
    # The transition logic — `auto` advances to `light`, etc.
    assert "this.mode === 'auto' ? 'light'" in body
    assert "this.mode === 'light' ? 'dark'" in body
    assert "'auto'" in body  # final fallback


def test_persisted_value_validation_clamps_unknown_to_auto(
    tmp_path: Path,
) -> None:
    """A corrupt localStorage entry (e.g. operator hand-edit) must
    not break the page — fall back to 'auto'."""
    client = TestClient(create_app(_config(tmp_path)))
    body = client.get("/").text
    assert "stored !== 'light'" in body
    assert "stored !== 'dark'" in body
    assert "stored !== 'auto'" in body


def test_localstorage_failures_are_swallowed(tmp_path: Path) -> None:
    """localStorage may throw in private browsing mode. The IIFE +
    cycle() must both catch and continue."""
    client = TestClient(create_app(_config(tmp_path)))
    body = client.get("/").text
    # Both the read and the write are wrapped in try/catch.
    assert "try { stored = window.localStorage.getItem" in body
    assert "try { window.localStorage.setItem('hm-theme', next)" in body


def test_toggle_button_aria_label_announces_mode(tmp_path: Path) -> None:
    """Screen readers must announce the current mode AND the action.
    Bound via `:aria-label` so it updates on every cycle."""
    client = TestClient(create_app(_config(tmp_path)))
    body = client.get("/").text
    assert ":aria-label=\"`Theme: ${mode}. Click to cycle.`\"" in body


def test_toggle_icons_distinguish_three_modes(tmp_path: Path) -> None:
    """Glyphs reinforce mode for color-vision-aware accessibility:
    ☀ light, ☾ dark, ◐ auto."""
    client = TestClient(create_app(_config(tmp_path)))
    body = client.get("/").text
    assert "'☀'" in body
    assert "'☾'" in body
    assert "'◐'" in body

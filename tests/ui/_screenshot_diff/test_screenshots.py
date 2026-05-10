"""Browser-driven screenshot regression tests (v13.0.0a1).

Gated behind `-m browser` like the rest of the v3.0.0a10 browser
suite. Skipped automatically in environments without Playwright +
chromium.

Surfaces covered (one snapshot per theme):

    dashboard          /
    project_detail     /projects/demo-browser
    fan_out            /tools/fan-out
    network            /network
    dispatcher_trace   /dispatcher/trace

Bootstrap workflow (one-time, after a deliberate visual change):

    HM_SCREENSHOT_BOOTSTRAP=1 \\
        uv run pytest tests/ui/_screenshot_diff/test_screenshots.py \\
                      -m browser

This pass writes `*__actual.png` files but does not call the assertion
helper — operators eyeball the actuals, then ``cp`` them onto the
baseline filenames. The next regular run wires up the assertion.
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.browser

pytest.importorskip("playwright")
pytest.importorskip("pytest_playwright")
pytest.importorskip("PIL")

from playwright.sync_api import Page  # noqa: E402

from .conftest import is_bootstrap_mode  # noqa: E402
from .helper import (  # noqa: E402
    VIEWPORT_HEIGHT,
    VIEWPORT_WIDTH,
    assert_screenshot_matches,
    baseline_path,
)

# (surface_name, route) — routes resolve under the `ui_url` fixture.
_SURFACES: tuple[tuple[str, str], ...] = (
    ("dashboard", "/"),
    ("project_detail", "/projects/demo-browser"),
    ("fan_out", "/tools/fan-out"),
    ("network", "/network"),
    ("dispatcher_trace", "/dispatcher/trace"),
)


def _set_theme(page: Page, theme: str) -> None:
    """Force the documented light/dark theme via the same Alpine helper
    the user-facing toggle uses (v12.0.0a7)."""
    # Set the persisted preference + apply the class on <html>. The
    # Alpine `themeToggle()` reads from localStorage on init, so we
    # set both for safety regardless of mount order.
    page.evaluate(
        f"""
        () => {{
            try {{ localStorage.setItem('hm-theme', {theme!r}); }} catch (_) {{}}
            const el = document.documentElement;
            el.classList.remove('dark', 'light');
            el.classList.add({theme!r});
        }}
        """
    )


@pytest.mark.parametrize("surface,route", _SURFACES)
@pytest.mark.parametrize("theme", ("dark", "light"))
def test_surface_matches_baseline(
    page: Page,
    ui_url: str,
    surface: str,
    route: str,
    theme: str,
) -> None:
    page.set_viewport_size({"width": VIEWPORT_WIDTH, "height": VIEWPORT_HEIGHT})
    page.goto(f"{ui_url}{route}")
    _set_theme(page, theme)
    # Allow a beat for any post-paint reflow (Alpine init, htmx swaps).
    page.wait_for_load_state("networkidle", timeout=5000)

    if is_bootstrap_mode() or not baseline_path(surface, theme).exists():
        # Persist actual.png next to the baseline so the operator can
        # bless it without re-running.
        actual = baseline_path(surface, theme).with_name(
            f"{surface}__{theme}__actual.png"
        )
        actual.write_bytes(page.screenshot(full_page=False, type="png"))
        pytest.skip(
            f"bootstrap: wrote {actual.name} — review and copy over "
            f"{baseline_path(surface, theme).name} to bless."
        )

    assert_screenshot_matches(page, surface, theme)

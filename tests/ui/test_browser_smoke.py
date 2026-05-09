"""Browser-driven smoke tests for the Harbormaster UI (v3.0.0a10).

Opt-in via `pytest -m browser`. Spins up harbormaster-ui on loopback
via the session-scoped `ui_url` fixture, drives Chromium through
the dashboard / project_detail / fan-out flows.

Run locally:
    uv sync --extra dev --extra ui-test
    uv run playwright install chromium
    uv run pytest -m browser tests/ui/

CI parity: see `.github/workflows/ci.yml` smoke-ui-browser job.
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.browser

# pytest-playwright provides the `page` fixture automatically once
# the [ui-test] extra is installed. importorskip keeps the file
# loadable in environments where it isn't.
pytest.importorskip("playwright")
pytest.importorskip("pytest_playwright")

from playwright.sync_api import Page, expect  # noqa: E402


def test_dashboard_renders_header(page: Page, ui_url: str) -> None:
    page.goto(f"{ui_url}/")
    expect(page.locator("h1")).to_contain_text("Harbormaster")


def test_dashboard_renders_bridge_status_panel(page: Page, ui_url: str) -> None:
    page.goto(f"{ui_url}/")
    # The bridge status panel is rendered by JS — wait for the badge.
    page.wait_for_selector("text=FleetQ Bridge", timeout=5000)
    # No FleetQ token present → either "disabled" or "configured" is fine,
    # but the badge must be in the DOM.
    expect(page.locator("text=FleetQ Bridge")).to_be_visible()


def test_dashboard_lists_seeded_project(page: Page, ui_url: str) -> None:
    page.goto(f"{ui_url}/")
    # Wait for the per-card project name to appear (the conftest seeded
    # `demo-browser`).
    page.wait_for_selector("text=demo-browser", timeout=5000)
    expect(page.locator("text=demo-browser").first).to_be_visible()


def test_dashboard_card_ask_button_toggles_form(page: Page, ui_url: str) -> None:
    """v3.0.0a7 inline ask form per card — clicking 'ask' must reveal
    a textarea inside the same card scope."""
    page.goto(f"{ui_url}/")
    page.wait_for_selector("text=demo-browser", timeout=5000)
    # The first ask button is associated with the demo-browser card.
    page.locator("button", has_text="ask").first.click()
    # Now there should be at least one textarea visible (the inline ask).
    expect(page.locator("textarea").first).to_be_visible()


def test_fan_out_page_loads_with_form(page: Page, ui_url: str) -> None:
    page.goto(f"{ui_url}/tools/fan-out")
    expect(page.locator("h2")).to_contain_text("Fan-out ask")
    expect(page.locator("button", has_text="Run fan-out")).to_be_visible()


def test_fan_out_url_state_round_trip(page: Page, ui_url: str) -> None:
    """v3.0.0a9 URL state — share link with q + targets pre-fills the form."""
    page.goto(
        f"{ui_url}/tools/fan-out?q=hello%20world&targets=demo-browser"
    )
    # Question textarea pre-filled.
    expect(page.locator("textarea").first).to_have_value("hello world")
    # Target checkbox checked.
    expect(page.locator('input[type="checkbox"][value="demo-browser"]')).to_be_checked()


def test_meta_tag_absent_when_no_auth_token(page: Page, ui_url: str) -> None:
    page.goto(f"{ui_url}/")
    # The conftest starts UI with no token → meta tag must not be in DOM.
    locator = page.locator('meta[name="hm-auth-token"]')
    expect(locator).to_have_count(0)

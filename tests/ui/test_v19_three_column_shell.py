"""v19.0.0a1: 3-column workspace shell — browser-driven verification.

Audits the runtime behavior the unit tests can't reach:

* All three landmarks (sidebar, main, inspector) are visible on `/`.
* Clicking the inspector collapse `«` button hides the inspector.
* Reload preserves the collapsed state via localStorage.

Opt-in via `pytest -m browser` — same gating as test_browser_smoke.py.
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.browser

pytest.importorskip("playwright")
pytest.importorskip("pytest_playwright")

from playwright.sync_api import Page, expect  # noqa: E402


def test_three_column_shell_landmarks_visible(page: Page, ui_url: str) -> None:
    """All three column landmarks render and are visible on first paint."""
    page.goto(f"{ui_url}/", wait_until="networkidle")
    expect(page.locator('aside[data-tour-step="sidebar"]')).to_be_visible()
    expect(page.locator('main[data-tour-step="main"]')).to_be_visible()
    expect(page.locator("#inspector")).to_be_visible()


def test_inspector_collapse_hides_panel_and_persists(
    page: Page, ui_url: str
) -> None:
    """Clicking «  collapses the inspector; localStorage carries the
    preference across a reload."""
    page.goto(f"{ui_url}/", wait_until="networkidle")
    inspector = page.locator("#inspector")
    expect(inspector).to_be_visible()

    # Trigger the collapse via the in-inspector close button.
    page.locator('#inspector button[aria-label="Collapse inspector"]').click()
    expect(inspector).to_be_hidden()

    # The grid columns shrink — sentinel: the floating expand button
    # appears so the user can re-open.
    expand_btn = page.locator('button[aria-label="Expand inspector"]')
    expect(expand_btn).to_be_visible()

    # Reload and confirm the state persisted.
    page.reload(wait_until="networkidle")
    expect(page.locator("#inspector")).to_be_hidden()
    expect(page.locator('button[aria-label="Expand inspector"]')).to_be_visible()

    # Re-expand for cleanliness — restores default state for any
    # subsequent test that might share this page.
    page.locator('button[aria-label="Expand inspector"]').click()
    expect(page.locator("#inspector")).to_be_visible()

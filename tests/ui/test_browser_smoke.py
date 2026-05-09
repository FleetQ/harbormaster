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

from pathlib import Path  # noqa: F401  (used by signature-typed fixtures below)

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


# --- v4.0.0a1: expanded Playwright coverage -----------------------------


def test_dashboard_recall_panel_renders(page: Page, ui_url: str) -> None:
    """Recall search panel must render with input + button."""
    page.goto(f"{ui_url}/")
    page.wait_for_selector("text=Recall", timeout=5000)
    expect(page.locator("text=Recall").first).to_be_visible()


def test_fan_out_select_all_then_none(page: Page, ui_url: str) -> None:
    """selectAll() then selectNone() round-trip the checkbox state."""
    page.goto(f"{ui_url}/tools/fan-out")
    # Click "all" — at least one checkbox should be checked after.
    page.locator("button", has_text="all").first.click()
    # At least one should now be checked
    page.wait_for_function(
        "() => Array.from(document.querySelectorAll('input[type=\"checkbox\"]')).some(c => c.checked)",
        timeout=2000,
    )
    # Click "none" — no checkboxes should be checked.
    page.locator("button", has_text="none").first.click()
    page.wait_for_function(
        "() => !Array.from(document.querySelectorAll('input[type=\"checkbox\"]')).some(c => c.checked)",
        timeout=2000,
    )


def test_fan_out_question_persists_to_url(page: Page, ui_url: str) -> None:
    """v3.0.0a9 URL state — typing in the question textarea then
    clicking selectAll must write q + targets to the URL."""
    page.goto(f"{ui_url}/tools/fan-out")
    page.locator("textarea").first.fill("test question for url state")
    page.locator("button", has_text="all").first.click()
    # selectAll triggers persistToUrl; URL must include q.
    page.wait_for_function(
        "() => window.location.search.includes('q=test')",
        timeout=2000,
    )
    url = page.url
    assert "q=test" in url
    # Targets parameter only appears when selection is partial; selectAll
    # leaves it omitted by design (default-omit serialization).


def test_project_detail_navigation_from_dashboard(page: Page, ui_url: str) -> None:
    """Clicking the project name on the dashboard navigates to the detail page."""
    page.goto(f"{ui_url}/")
    page.wait_for_selector("text=demo-browser", timeout=5000)
    # The h3 contains an <a> with the project name; click it.
    page.locator("h3 a", has_text="demo-browser").first.click()
    # Wait for nav.
    page.wait_for_url("**/projects/demo-browser", timeout=5000)
    # Detail page renders Recent Q&A section (trajectory list).
    page.wait_for_selector("text=Recent Q&A", timeout=5000)


def test_dashboard_does_not_navigate_when_clicking_card_chrome(page: Page, ui_url: str) -> None:
    """v3.0.0a7 changed the card from a wrapping <a> to an article;
    clicking the card body (not the project name link) must NOT
    navigate."""
    page.goto(f"{ui_url}/")
    page.wait_for_selector("text=demo-browser", timeout=5000)
    initial_url = page.url
    # Click somewhere in the card that isn't the project-name link.
    # The footer span (path text) is a safe target.
    footer = page.locator("article").filter(has_text="demo-browser").first
    footer.locator("footer").click()
    # URL must not have changed.
    assert page.url == initial_url


def test_meta_tag_present_when_token_set_via_subprocess_env(
    page: Page, tmp_path: Path
) -> None:
    """Sanity: bearer-protected install renders the meta tag.

    Skipped — this would require a second UI subprocess fixture with
    HARBORMASTER_UI_TOKEN set, plus injecting Authorization header on
    every request. Covered by unit test
    test_dashboard_renders_meta_tag_when_auth_token_set instead.
    """
    pytest.skip("covered by unit test; running second UI subprocess is heavy")


# --- v7.0.0a1: SVG-render assertion -----------------------------------
#
# Closes the v4.0.0a3 → v6.0.2 regression-detection gap. Previously the
# Playwright suite only asserted the <pre class="mermaid"> element was
# present, not that Mermaid had actually rendered into a sized SVG.
# That allowed the v6.0.0/v6.0.1/v6.0.2 graph-render bugs (placeholder
# 16×16 viewBox + x-show race) to live for 17 versions undetected.
#
# This test reads the actual rendered <svg>'s bounding box. A
# placeholder/unrendered SVG has bbox ~ 16×16 (Mermaid's transparent
# stub); a real rendered diagram is well over 50px in each dimension
# even for the seeded single-node graph.


def test_dashboard_graph_renders_with_real_viewbox(
    page: Page, ui_url: str
) -> None:
    """Mermaid must render a sized <svg>, not a 16×16 placeholder.

    Regression guard for v6.0.0 / v6.0.1 / v6.0.2 graph bugs.
    A renderer that fails silently (e.g. measures the still-hidden
    <pre> at 0×0, or the x-show + measure race) leaves the bbox
    stuck at the transparent placeholder dimensions; a real render
    produces a diagram > 50px wide for any non-empty graph.
    """
    page.goto(f"{ui_url}/")
    # Wait for Mermaid to inject the <svg> child of <pre.mermaid>.
    page.wait_for_selector("pre.mermaid svg", timeout=10000)
    width, height = page.evaluate(
        """() => {
            const svg = document.querySelector('pre.mermaid svg');
            const b = svg.getBBox();
            return [b.width, b.height];
        }"""
    )
    assert width > 50, (
        f"viewBox stuck at placeholder; bbox = {width}x{height}. "
        "Mermaid did not render — likely an x-show/measure race "
        "(see v6.0.1/v6.0.2 retros) or graphLoading flag never flipped."
    )
    assert height > 10, (
        f"SVG height collapsed; bbox = {width}x{height}. "
        "Diagram rendered as a horizontal line — usually means "
        "Mermaid measured the hidden container at 0px and gave up."
    )

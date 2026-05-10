"""v18.0.0a2 — trace waterfall hover/focus tooltip tests.

Adds an aria-describedby tooltip to each span row in the dispatcher
trace waterfall. Tooltip reveal is driven by Tailwind's
`group-hover` + `group-focus-within` (no new tooltip library), and
the row itself is `tabindex=0` so keyboard users can reach it.

Tests assert template-level wiring only (the page-level Playwright
bundle in `test_smoke_bundle_v13` stays the visual gate).
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from harbormaster.config import HarbormasterConfig, ProjectsConfig
from harbormaster.fleetq import get_dispatcher_stats
from harbormaster.ui.app import create_app


@pytest.fixture
def tip_client(tmp_path: Path) -> TestClient:
    (tmp_path / "projects").mkdir(parents=True, exist_ok=True)
    cfg = HarbormasterConfig(
        projects=ProjectsConfig(glob=[str(tmp_path / "projects" / "*")]),
    )
    return TestClient(create_app(cfg))


@pytest.fixture(autouse=True)
def _reset_stats() -> None:
    get_dispatcher_stats().reset()


def test_tooltip_element_present(tip_client: TestClient) -> None:
    """Each span row carries a `data-span-tooltip` element."""
    body = tip_client.get("/dispatcher").text
    assert "data-span-tooltip" in body
    # The tooltip must use role=tooltip for assistive tech.
    assert 'role="tooltip"' in body


def test_tooltip_aria_describedby_link(tip_client: TestClient) -> None:
    """Span row is aria-describedby linked to its tooltip element."""
    body = tip_client.get("/dispatcher").text
    # Row binds `aria-describedby` to a deterministic id derived from
    # span_id; tooltip element binds the matching `id`.
    assert ':aria-describedby="`span-tip-${span.span_id}`"' in body
    assert ':id="`span-tip-${span.span_id}`"' in body


def test_tooltip_keyboard_reachable(tip_client: TestClient) -> None:
    """The span row is keyboard-focusable (tabindex=0) so focus
    can trigger the tooltip via group-focus-within."""
    body = tip_client.get("/dispatcher").text
    # Row carries tabindex=0 + the focus-within reveal class.
    assert 'tabindex="0"' in body
    assert "group-focus-within:block" in body
    # Hover reveal preserved alongside focus reveal.
    assert "group-hover:block" in body


def test_tooltip_summary_helper_exists(tip_client: TestClient) -> None:
    """`spanTooltipSummary(span)` is the centralized format helper."""
    body = tip_client.get("/dispatcher").text
    # The Alpine binding must call the helper (not inline the format).
    assert 'x-text="spanTooltipSummary(span)"' in body
    # The factory must define the helper.
    assert "spanTooltipSummary(span)" in body
    # Format pieces — name, duration_ms, ok/error, and attribute pairs.
    assert "span.duration_ms" in body
    assert "span.ok ? 'ok' : 'error'" in body
    # First two attributes — project + span_id — both surface in the
    # tooltip summary string.
    assert "['project', span.project" in body
    assert "['span_id', span.span_id" in body


def test_tooltip_does_not_introduce_new_dependency(tip_client: TestClient) -> None:
    """No new tooltip JS lib — reuse Tailwind utility classes."""
    body = tip_client.get("/dispatcher").text
    # Sanity: the template still imports nothing new.
    assert "tippy" not in body.lower()
    assert "popperjs" not in body.lower()
    assert "floating-ui" not in body.lower()

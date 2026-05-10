"""Fixtures for the screenshot-diff harness (v13.0.0a1).

Reuses the parent `tests/ui/conftest.py` `ui_url` fixture. The
`screenshot_page` fixture sets a fixed viewport before yielding the
Playwright `page` so callers don't have to remember.

Bootstrap mode: when ``HM_SCREENSHOT_BOOTSTRAP=1`` is set in the
environment, missing-baseline assertions inside ``helper.py`` would
still raise — instead, run::

    HM_SCREENSHOT_BOOTSTRAP=1 pytest tests/ui/_screenshot_diff/ -m browser

and then ``cp tests/ui/_screenshot_diff/baseline/*__actual.png`` over
the corresponding baseline filenames. The bootstrap env var is read
by the surface-walker test below to skip assertion calls and instead
just write the actual.png file.
"""
from __future__ import annotations

import os

import pytest

# Surfaces × themes the harness covers. Ordering matters only for
# stable test-id output.
SURFACES: tuple[str, ...] = (
    "dashboard",
    "project_detail",
    "fan_out",
    "network",
    "dispatcher_trace",
)
THEMES: tuple[str, ...] = ("dark", "light")


def is_bootstrap_mode() -> bool:
    """Return True when running the one-off baseline-capture pass."""
    return os.environ.get("HM_SCREENSHOT_BOOTSTRAP") == "1"


@pytest.fixture
def screenshot_page(page):  # type: ignore[no-untyped-def]
    """Yield a Playwright page already sized to the harness viewport.

    The deliberately-untyped signature avoids importing playwright at
    module import time — the parent conftest's `ui_url` fixture already
    handles `pytest.importorskip`.
    """
    from .helper import VIEWPORT_HEIGHT, VIEWPORT_WIDTH

    page.set_viewport_size({"width": VIEWPORT_WIDTH, "height": VIEWPORT_HEIGHT})
    yield page

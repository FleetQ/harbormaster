"""Pixel-diff helper for screenshot regression tests (v13.0.0a1).

The harness captures a Playwright PNG screenshot at a fixed viewport,
compares it to a committed baseline under `baseline/`, and asserts
that the bounding-box pixel diff is below a tolerance (default 0.5%).

Why 0.5% tolerance? Anti-aliasing on font glyphs varies between
chromium versions and even between freshly-launched browser contexts.
Empirically the dashboard surface produced ~0.05% diffs on identical
input across two consecutive runs; 0.5% gives a 10x safety margin
while still catching genuine palette / layout shifts (which produce
multi-percent diffs).

The diff is computed via `Pillow.ImageChops.difference` and reduced
to `(non_zero_pixels) / (width * height)`. When the assertion fails
we write `actual.png` and `diff.png` next to the baseline so the
operator can eyeball what changed.
"""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from playwright.sync_api import Page  # noqa: F401


# Fixed viewport so the baseline is reproducible across machines.
# 1280x720 matches the dashboard's design width and is the default
# Playwright viewport — using the default removes one variable.
VIEWPORT_WIDTH = 1280
VIEWPORT_HEIGHT = 720

# 0.5% pixel-diff tolerance. See module docstring.
DEFAULT_TOLERANCE = 0.005

BASELINE_DIR = Path(__file__).parent / "baseline"


def baseline_path(surface: str, theme: str) -> Path:
    """Return the path to the committed baseline PNG for surface+theme."""
    return BASELINE_DIR / f"{surface}__{theme}.png"


def assert_screenshot_matches(
    page: Page,
    surface: str,
    theme: str,
    *,
    tolerance: float = DEFAULT_TOLERANCE,
) -> None:
    """Capture a screenshot of `page` and compare it to the baseline.

    Args:
        page: Playwright page already navigated + settled (callers should
            await any explicit `wait_for_selector` before calling).
        surface: Logical surface name (e.g. ``"dashboard"``). Used for
            the baseline filename.
        theme: ``"dark"`` or ``"light"``. The harness does NOT toggle
            the theme — callers are responsible for setting the theme
            before calling (e.g. via the ``themeToggle()`` Alpine helper).
        tolerance: Maximum allowed fraction of differing pixels.

    Raises:
        AssertionError: when the diff exceeds tolerance, or when no
            baseline exists yet (callers can bootstrap by passing
            ``HM_SCREENSHOT_BOOTSTRAP=1``; see ``conftest.py``).
    """
    from PIL import Image, ImageChops

    baseline = baseline_path(surface, theme)
    actual_path = baseline.with_name(f"{surface}__{theme}__actual.png")
    diff_path = baseline.with_name(f"{surface}__{theme}__diff.png")

    # Capture at fixed viewport. Full page would change height when
    # content changes — we want a stable framing window instead.
    page.set_viewport_size({"width": VIEWPORT_WIDTH, "height": VIEWPORT_HEIGHT})
    actual_bytes = page.screenshot(full_page=False, type="png")
    actual_path.write_bytes(actual_bytes)

    if not baseline.exists():
        raise AssertionError(
            f"No baseline at {baseline}; bootstrap by copying "
            f"{actual_path.name} to {baseline.name} after visual review."
        )

    actual_img = Image.open(actual_path).convert("RGB")
    baseline_img = Image.open(baseline).convert("RGB")

    if actual_img.size != baseline_img.size:
        raise AssertionError(
            f"Size mismatch for {surface}/{theme}: "
            f"baseline={baseline_img.size} actual={actual_img.size}"
        )

    diff_img = ImageChops.difference(actual_img, baseline_img)
    bbox = diff_img.getbbox()
    if bbox is None:
        # Identical — nothing to do.
        return

    # Count differing pixels (any channel non-zero). We use the bbox
    # luminance histogram so we don't depend on Pillow's `getdata()`
    # iterator (deprecated for removal in Pillow 14, 2027-10-15).
    width, height = actual_img.size
    total = width * height
    grey = diff_img.convert("L")
    histogram = grey.histogram()
    # histogram[0] = count of zero-difference pixels; everything else differs.
    differing = total - histogram[0]
    fraction = differing / total

    if fraction > tolerance:
        # Persist the diff for debugging.
        diff_img.save(diff_path)
        raise AssertionError(
            f"Screenshot diff for {surface}/{theme} exceeds tolerance: "
            f"{fraction * 100:.3f}% differ (limit {tolerance * 100:.3f}%). "
            f"See {actual_path} vs {baseline} (diff: {diff_path})."
        )

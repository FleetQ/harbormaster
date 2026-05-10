"""Unit tests for the screenshot-diff helper (v13.0.0a1).

These run in the regular (non-browser) pytest pass — they exercise
the diff math on synthetic in-memory PNGs so we don't depend on
Playwright + chromium being installed.

The browser-driven harness test lives in `test_screenshots.py` and
is gated behind `-m browser`.
"""
from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("PIL")

from PIL import Image  # noqa: E402

from . import helper  # noqa: E402


def _solid(color: tuple[int, int, int], size: tuple[int, int] = (32, 32)) -> Image.Image:
    return Image.new("RGB", size, color)


def test_identical_images_pass(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(helper, "BASELINE_DIR", tmp_path)
    img = _solid((10, 20, 30))
    img.save(tmp_path / "surface__dark.png")

    class _StubPage:
        def set_viewport_size(self, size: dict[str, int]) -> None:
            pass

        def screenshot(self, *, full_page: bool, type: str) -> bytes:
            buf = tmp_path / "_buf.png"
            img.save(buf)
            return buf.read_bytes()

    helper.assert_screenshot_matches(_StubPage(), "surface", "dark")  # type: ignore[arg-type]


def test_one_pixel_change_within_tolerance(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(helper, "BASELINE_DIR", tmp_path)
    base = _solid((10, 20, 30), (32, 32))
    base.save(tmp_path / "surface__dark.png")
    actual = base.copy()
    # 1 differing pixel out of 1024 = ~0.1%, well under 0.5% default.
    actual.putpixel((0, 0), (200, 0, 0))

    class _StubPage:
        def set_viewport_size(self, size: dict[str, int]) -> None:
            pass

        def screenshot(self, *, full_page: bool, type: str) -> bytes:
            buf = tmp_path / "_buf.png"
            actual.save(buf)
            return buf.read_bytes()

    helper.assert_screenshot_matches(_StubPage(), "surface", "dark")  # type: ignore[arg-type]


def test_large_change_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(helper, "BASELINE_DIR", tmp_path)
    base = _solid((10, 20, 30), (32, 32))
    base.save(tmp_path / "surface__dark.png")
    actual = _solid((200, 0, 0), (32, 32))  # entirely different

    class _StubPage:
        def set_viewport_size(self, size: dict[str, int]) -> None:
            pass

        def screenshot(self, *, full_page: bool, type: str) -> bytes:
            buf = tmp_path / "_buf.png"
            actual.save(buf)
            return buf.read_bytes()

    with pytest.raises(AssertionError, match="exceeds tolerance"):
        helper.assert_screenshot_matches(_StubPage(), "surface", "dark")  # type: ignore[arg-type]


def test_missing_baseline_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(helper, "BASELINE_DIR", tmp_path)
    img = _solid((10, 20, 30))

    class _StubPage:
        def set_viewport_size(self, size: dict[str, int]) -> None:
            pass

        def screenshot(self, *, full_page: bool, type: str) -> bytes:
            buf = tmp_path / "_buf.png"
            img.save(buf)
            return buf.read_bytes()

    with pytest.raises(AssertionError, match="No baseline"):
        helper.assert_screenshot_matches(_StubPage(), "missing", "dark")  # type: ignore[arg-type]


def test_size_mismatch_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(helper, "BASELINE_DIR", tmp_path)
    base = _solid((10, 20, 30), (32, 32))
    base.save(tmp_path / "surface__dark.png")
    actual = _solid((10, 20, 30), (16, 16))

    class _StubPage:
        def set_viewport_size(self, size: dict[str, int]) -> None:
            pass

        def screenshot(self, *, full_page: bool, type: str) -> bytes:
            buf = tmp_path / "_buf.png"
            actual.save(buf)
            return buf.read_bytes()

    with pytest.raises(AssertionError, match="Size mismatch"):
        helper.assert_screenshot_matches(_StubPage(), "surface", "dark")  # type: ignore[arg-type]


def test_baseline_path_helper(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(helper, "BASELINE_DIR", tmp_path)
    p = helper.baseline_path("dashboard", "dark")
    assert p == tmp_path / "dashboard__dark.png"


def test_default_tolerance_constant() -> None:
    """Sanity-check that nobody accidentally bumps the tolerance to 100%."""
    assert 0 < helper.DEFAULT_TOLERANCE < 0.05


def test_viewport_constants_match_design() -> None:
    """The harness baselines are captured at 1280x720; locking the
    constant prevents accidental viewport drift between runs."""
    assert helper.VIEWPORT_WIDTH == 1280
    assert helper.VIEWPORT_HEIGHT == 720

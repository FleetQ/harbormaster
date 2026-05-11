"""v21.0.0a4: WCAG AA contrast verification for light-mode tokens.

The v12.0.0a7 toggle introduced a `theme-light` token set in
`tailwind.input.css` but the actual luminance values were never audited.
This test parses the OKLCH tokens out of the CSS source, converts them
to relative luminance via the standard OKLab → linear sRGB pipeline
(Björn Ottosson, https://bottosson.github.io/posts/oklab/), and asserts
WCAG AA contrast ratios:

  - 4.5:1 for body text (`foreground`, `foreground-muted`,
    `foreground-subtle`, `foreground-dim`, `accent`, `accent-strong`).
  - 3:1 for state-conveying UI components (`border-strong`, used by
    focused inputs / pressed buttons).

`border` / `border-subtle` are purely decorative and not subject to
3:1 (they don't convey state). Tested for non-regression only — the
ratio must stay > 1.0 (i.e. actually visible against the surface).

If this test ever fails: tune the relevant token's L (lightness) down
until the ratio crosses the floor. Hue / chroma can stay the same to
preserve the on-brand violet.
"""
from __future__ import annotations

import math
import re
from pathlib import Path

import pytest

_STATIC_CSS = (
    Path(__file__).parent.parent.parent
    / "src" / "harbormaster" / "ui" / "static" / "tailwind.input.css"
)


# --- OKLCH → contrast helpers ---------------------------------------- #

def _oklch_to_linear_rgb(L: float, C: float, h_deg: float) -> tuple[float, float, float]:  # noqa: N803
    """OKLab → linear sRGB. Reference: bottosson.github.io/posts/oklab/."""
    h = math.radians(h_deg)
    a = C * math.cos(h)
    b = C * math.sin(h)
    l_ = L + 0.3963377774 * a + 0.2158037573 * b
    m_ = L - 0.1055613458 * a - 0.0638541728 * b
    s_ = L - 0.0894841775 * a - 1.2914855480 * b
    l, m, s = l_ ** 3, m_ ** 3, s_ ** 3  # noqa: E741
    r = +4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s
    g = -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s
    bl = -0.0041960863 * l - 0.7034186147 * m + 1.7076147010 * s
    return r, g, bl


def _luminance(r: float, g: float, b: float) -> float:
    """WCAG relative luminance (already linear)."""
    def c(x):
        return max(0.0, min(1.0, x))
    return 0.2126 * c(r) + 0.7152 * c(g) + 0.0722 * c(b)


def _contrast(fg: tuple[float, float, float], bg: tuple[float, float, float]) -> float:
    l1 = _luminance(*_oklch_to_linear_rgb(*fg))
    l2 = _luminance(*_oklch_to_linear_rgb(*bg))
    hi, lo = max(l1, l2), min(l1, l2)
    return (hi + 0.05) / (lo + 0.05)


# --- parse `html.theme-light` block from the CSS source -------------- #

_TOKEN_RE = re.compile(
    r"--color-([a-z0-9-]+):\s*oklch\(\s*([0-9.]+)\s+([0-9.]+)\s+([0-9.]+)\s*\)"
)


def _parse_light_tokens() -> dict[str, tuple[float, float, float]]:
    src = _STATIC_CSS.read_text(encoding="utf-8")
    # Grab the explicit `html.theme-light { … }` block; that's the one
    # used in tests + the toggle's persisted state. The @media block
    # carries the same values and is asserted to match below.
    m = re.search(r"html\.theme-light\s*\{([^}]+)\}", src, re.DOTALL)
    assert m, "Could not locate html.theme-light block in tailwind.input.css"
    tokens: dict[str, tuple[float, float, float]] = {}
    for name, L, C, h in _TOKEN_RE.findall(m.group(1)):  # noqa: N806
        tokens[name] = (float(L), float(C), float(h))
    return tokens


# --- assertions ------------------------------------------------------ #

@pytest.fixture(scope="module")
def light() -> dict[str, tuple[float, float, float]]:
    return _parse_light_tokens()


# Text tokens must clear 4.5:1 against every surface they could land on.
_TEXT_PAIRS = [
    ("foreground", "surface-0"),
    ("foreground", "surface-1"),
    ("foreground", "surface-2"),
    ("foreground", "surface-3"),
    ("foreground-muted", "surface-0"),
    ("foreground-muted", "surface-1"),
    ("foreground-muted", "surface-2"),
    ("foreground-muted", "surface-3"),
    ("foreground-subtle", "surface-0"),
    ("foreground-subtle", "surface-1"),
    ("foreground-subtle", "surface-2"),
    ("foreground-subtle", "surface-3"),
    ("foreground-dim", "surface-0"),
    ("foreground-dim", "surface-1"),
    ("foreground-dim", "surface-2"),
    ("foreground-dim", "surface-3"),
    ("accent", "surface-0"),
    ("accent", "surface-1"),
    ("accent", "surface-2"),
    ("accent", "surface-3"),
    ("accent-strong", "surface-0"),
    ("accent-strong", "surface-1"),
    ("accent-strong", "surface-2"),
    ("accent-strong", "surface-3"),
]


@pytest.mark.parametrize("fg,bg", _TEXT_PAIRS)
def test_text_token_meets_aa(
    light: dict[str, tuple[float, float, float]], fg: str, bg: str,
) -> None:
    """Every text-bearing token must clear 4.5:1 on every surface."""
    ratio = _contrast(light[fg], light[bg])
    assert ratio >= 4.5, (
        f"{fg} on {bg}: contrast {ratio:.2f} < 4.5 (WCAG AA). "
        f"Lower the L value of `--color-{fg}` in html.theme-light."
    )


# `border-strong` is the state-conveying border (focused inputs) — needs 3:1.
@pytest.mark.parametrize("bg", ["surface-0", "surface-1", "surface-2", "surface-3"])
def test_border_strong_meets_ui_floor(
    light: dict[str, tuple[float, float, float]], bg: str,
) -> None:
    ratio = _contrast(light["border-strong"], light[bg])
    assert ratio >= 3.0, (
        f"border-strong on {bg}: contrast {ratio:.2f} < 3.0 "
        f"(WCAG AA UI component). Lower L of --color-border-strong."
    )


# Non-regression floor for decorative borders — must stay visible (>1.05).
@pytest.mark.parametrize("border", ["border", "border-subtle"])
def test_decorative_borders_are_visible(
    light: dict[str, tuple[float, float, float]], border: str,
) -> None:
    ratio = _contrast(light[border], light["surface-1"])
    assert ratio > 1.05, (
        f"{border} on surface-1: contrast {ratio:.2f} is too close to 1.0; "
        f"border would be invisible."
    )


def test_media_query_block_matches_explicit_class() -> None:
    """The `@media (prefers-color-scheme: light)` block should carry the
    same OKLCH values as `html.theme-light` — otherwise auto-mode and
    explicit-light diverge."""
    src = _STATIC_CSS.read_text(encoding="utf-8")
    media = re.search(
        r"@media \(prefers-color-scheme: light\)\s*\{\s*:root\s*\{([^}]+)\}",
        src, re.DOTALL,
    )
    assert media, "@media (prefers-color-scheme: light) :root block missing"
    media_tokens = {
        name: (float(L), float(C), float(h))
        for name, L, C, h in _TOKEN_RE.findall(media.group(1))
    }
    explicit_tokens = _parse_light_tokens()
    # Only compare tokens defined in both blocks (they should be the same set).
    common = set(media_tokens) & set(explicit_tokens)
    assert common, "Light-mode token sets are empty / failed to parse"
    for name in common:
        assert media_tokens[name] == explicit_tokens[name], (
            f"Token --color-{name} differs between @media and html.theme-light"
        )

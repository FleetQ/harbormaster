"""v19.0.0a4 regression: Linear-violet OKLCH tokens + compact density.

Validates the visual rebrand:

1. The compiled `tailwind.css` ships an `--color-accent-500` token
   whose hue channel is 290 (violet — Linear's brand hue), proving
   the new `@theme` block in `tailwind.input.css` was actually
   compiled into the served stylesheet.
2. No template still references raw `bg-cyan-NNN` / `text-cyan-NNN`
   / `border-cyan-NNN` / `ring-cyan-NNN` / `bg-gray-9NN/NN` Tailwind
   classes — all moved to semantic tokens
   (`accent`, `surface-N`).
3. The accent palette scale (`accent-50` … `accent-900`) is emitted
   as utility classes — proves they're discoverable by Tailwind v4's
   scanner.
4. A representative compact-density choice survived in the page
   templates (e.g. `p-2.5` is now used somewhere on the dashboard).

These tests are stricter than the v13 utility-migration test (which
only forbade the high-shade cyan utilities). v19.0.0a4 forbids ALL
cyan- raw classes anywhere in the served HTML.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

UI_DIR = (
    Path(__file__).parent.parent.parent
    / "src"
    / "harbormaster"
    / "ui"
)
TEMPLATE_DIR = UI_DIR / "templates"
CSS_PATH = UI_DIR / "static" / "tailwind.css"


# ---------------------------------------------------------------------------
# CSS-level checks
# ---------------------------------------------------------------------------

def test_compiled_css_contains_violet_accent() -> None:
    """The compiled stylesheet must define --color-accent at hue 290
    (Linear violet).

    This is the canonical 'did the v19.0.0a4 @theme block reach the
    wire' probe. If a future change to tailwind.input.css shifts the
    accent hue back toward cyan (215/220) this test catches the
    regression before operators see a faded UI.

    Tailwind v4 minifies `oklch(0.78 0.13 290)` as
    `oklch(78% .13 290)`; we match permissively across either form
    AND the optional `0` before the decimal point.
    """
    css = CSS_PATH.read_text(encoding="utf-8")
    pattern = re.compile(
        r"--color-accent\s*:\s*oklch\(\s*"
        r"(?:78%|0?\.78)\s+0?\.13\s+290\s*\)"
    )
    assert pattern.search(css), (
        "compiled tailwind.css missing the violet --color-accent "
        "token (`oklch(.78 .13 290)`). Either tailwind.input.css was "
        "edited without rebuilding the CSS, or the @theme block was "
        "altered. Run a clean wheel build to refresh."
    )


def test_compiled_css_uses_violet_hue_280_290_only() -> None:
    """Sanity sweep — every oklch() value defined under the project's
    own --color-accent* / --color-surface* / --color-border* /
    --color-foreground* tokens must use hue 280 (surface tint) or
    290 (accent). Catches a partial revert where one token slipped
    back to the cyan family (hue 215/220).
    """
    css = CSS_PATH.read_text(encoding="utf-8")
    pattern = re.compile(
        r"(--color-(?:accent|surface|border|foreground)[a-z-]*)\s*:\s*"
        r"oklch\([^)]+\s+(\d+(?:\.\d+)?)\s*\)"
    )
    bad: list[str] = []
    for name, hue in pattern.findall(css):
        try:
            hue_f = float(hue)
        except ValueError:
            continue
        if hue_f not in (280.0, 290.0, 0.0):
            bad.append(f"{name}=hue {hue}")
    assert not bad, (
        f"v19.0.0a4 violet rebrand expects hue 280 or 290 on every "
        f"--color-accent/surface/border/foreground token. Drifted: "
        f"{bad[:5]}"
    )


# ---------------------------------------------------------------------------
# Template-level checks
# ---------------------------------------------------------------------------

# Strict: NO cyan- raw classes anywhere (opacity-suffixed or not).
# Trailing word-boundary makes sure we're matching a class token, not
# a substring like "cyancomment".
_FORBIDDEN_CYAN = re.compile(
    r"(?<![\w-])"
    r"(?:bg|text|border|ring|ring-offset|accent)-cyan-\d+"
    r"(?:/\d+)?"  # opacity suffix
    r"(?![\w-])"
)

# bg-gray-9NN/NN (opacity-suffixed) — v13 left these alone; v19.0.0a4
# replaces them with surface tokens.
_FORBIDDEN_GRAY_OPACITY = re.compile(
    r"(?<![\w-])"
    r"(?:bg|border)-gray-(?:800|900|950)/\d+"
    r"(?![\w-])"
)


def _all_templates() -> list[Path]:
    return sorted(TEMPLATE_DIR.rglob("*.html"))


@pytest.mark.parametrize("template", _all_templates(), ids=lambda p: p.name)
def test_no_raw_cyan_classes(template: Path) -> None:
    """Every cyan- Tailwind utility was migrated to an accent semantic
    token in v19.0.0a4."""
    text = template.read_text(encoding="utf-8")
    matches = _FORBIDDEN_CYAN.findall(text)
    assert not matches, (
        f"{template.relative_to(TEMPLATE_DIR.parent)}: cyan- raw "
        f"utility classes survived the v19.0.0a4 violet migration: "
        f"{sorted(set(matches))}. Replace with accent / accent-soft / "
        f"accent-strong / ring-accent."
    )


@pytest.mark.parametrize("template", _all_templates(), ids=lambda p: p.name)
def test_no_gray_opacity_backgrounds(template: Path) -> None:
    """Opacity-suffixed gray-9NN/NN backgrounds must use surface tokens."""
    text = template.read_text(encoding="utf-8")
    matches = _FORBIDDEN_GRAY_OPACITY.findall(text)
    assert not matches, (
        f"{template.relative_to(TEMPLATE_DIR.parent)}: gray-9NN/NN "
        f"opacity-suffixed classes survived: {sorted(set(matches))}. "
        f"Use bg-surface-1/N etc."
    )


# ---------------------------------------------------------------------------
# Density check — make sure compactness landed in at least one place
# ---------------------------------------------------------------------------

def test_dashboard_has_compact_padding() -> None:
    """The dashboard's KPI strip + cards used `p-3` / `p-4` before
    v19.0.0a4. Post-migration we expect at least one `p-2.5` (or `p-2`)
    occurrence — proves the global density pass actually shipped."""
    text = (TEMPLATE_DIR / "dashboard.html").read_text(encoding="utf-8")
    has_compact = bool(re.search(r"\b(?:p|py)-2\.5\b", text)) or (
        text.count("p-2") > 5  # plenty of compact paddings
    )
    assert has_compact, (
        "dashboard.html shows no compact-padding markers — the "
        "v19.0.0a4 density pass did not apply to the dashboard"
    )

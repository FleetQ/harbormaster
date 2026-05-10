"""Regression tests for the v13.0.0a2 Tailwind utility migration.

Ensures that high-confidence raw color utilities (text-gray-*,
bg-gray-9*, border-gray-*) which the migration script swept never
sneak back in via copy-paste from external snippets.

The list of forbidden classes is intentionally narrow — it covers
the surface that the v13.0.0a2 migration completely eradicated.
Opacity-suffixed variants (`bg-cyan-900/50`, `border-rose-700/50`)
are still allowed; they're tracked for v13.0.0a3+ semantic-token-
with-opacity work.

If a future template legitimately needs to render a raw color
utility, prefer adding a new semantic token to `tailwind.input.css`
over disabling this test.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

TEMPLATE_DIR = (
    Path(__file__).parent.parent.parent
    / "src"
    / "harbormaster"
    / "ui"
    / "templates"
)


# Utilities the v13.0.0a2 migration eradicated. Trailing word-boundary
# (negative lookahead for `/`, `\w`, `-`) so opacity variants like
# `bg-gray-950/40` still pass — those are intentionally out of scope.
_FORBIDDEN_PATTERN = re.compile(
    r"(?<![\w-])"
    r"(?:"
    r"text-gray-(?:100|200|300|400|500|600|700)"
    r"|text-cyan-(?:100|200|300|400|500|600|700)"
    r"|text-emerald-(?:300|400)"
    r"|text-amber-(?:300|400)"
    r"|text-rose-(?:300|400)"
    r"|text-red-(?:300|400)"
    r"|text-purple-(?:300|400)"
    r"|bg-gray-(?:800|900|950)"
    r"|bg-cyan-(?:600|700|800)"
    r"|border-gray-(?:700|800|900)"
    r"|border-cyan-(?:700|800)"
    r"|border-amber-700"
    r")"
    r"(?![\w/-])"
)


def _all_templates() -> list[Path]:
    return sorted(TEMPLATE_DIR.rglob("*.html"))


@pytest.mark.parametrize("template", _all_templates(), ids=lambda p: p.name)
def test_template_uses_only_semantic_tokens(template: Path) -> None:
    """No raw color utility from the v13.0.0a2 migration list survives."""
    text = template.read_text(encoding="utf-8")
    matches = _FORBIDDEN_PATTERN.findall(text)
    assert not matches, (
        f"{template.relative_to(TEMPLATE_DIR.parent)}: found raw color "
        f"utilities that should be semantic tokens: {sorted(set(matches))}. "
        f"Run `python scripts/migrate_tailwind_utilities.py`."
    )


def test_vendored_css_includes_semantic_utilities() -> None:
    """Sanity-check the compiled tailwind.css ships the semantic-token
    utility classes the templates depend on. Catches the case where
    `@source` directive in tailwind.input.css gets dropped."""
    css = (TEMPLATE_DIR.parent / "static" / "tailwind.css").read_text(
        encoding="utf-8"
    )
    # Sample one of each family — full enumeration would be brittle.
    for klass in [
        ".text-foreground",
        ".text-foreground-muted",
        ".text-foreground-subtle",
        ".text-accent",
        ".text-success",
        ".text-warning",
        ".text-danger",
        ".bg-surface-1",
        ".bg-surface-2",
        ".bg-surface-3",
        ".bg-accent",
        ".border-border",
        ".border-border-strong",
        ".border-accent",
    ]:
        assert klass in css, (
            f"vendored tailwind.css missing utility class {klass}; "
            f"the @source directive in tailwind.input.css may have "
            f"been dropped or the CSS hasn't been recompiled."
        )

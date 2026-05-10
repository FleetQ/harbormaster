"""Phase 7 distribution audit (v8.0.0a7).

The v8 plan called for:
  1. Drop HTMX (confirmed unused).
  2. Add semantic OKLCH color tokens.
  3. Vendor Tailwind v4 + migrate utility classes to semantic tokens.

Items 1 + 2 ship in v8.0.0a7.

Item 3 (full Tailwind v4 vendor + migration) was deferred to v9 —
the per-class migration plus operator distribution decision (vendor
the v4 CLI binary vs. add a build step in pyproject.toml) is too
large to fit cleanly inside one alpha without forcing risky
last-minute ops choices. The split is documented in the v8.0.0a7
sprint retro and the v8.0.0 GA notes.

This audit enforces what *did* ship:

* No `hx-*` attributes in any template (post-Phase 1 baseline).
* No `unpkg.com/htmx.org` script tag in `base.html`.
* The semantic OKLCH token set is defined under `:root` in
  `base.html` with the canonical `--hm-*` prefix.
* `[x-cloak] { display: none !important; }` rule centralized in
  `base.html` (used to live as inline-style copies).
"""
from __future__ import annotations

from pathlib import Path

import pytest

TEMPLATE_DIR = (
    Path(__file__).parent.parent.parent
    / "src"
    / "harbormaster"
    / "ui"
    / "templates"
)


def _all_templates() -> list[Path]:
    return sorted(TEMPLATE_DIR.rglob("*.html"))


@pytest.mark.parametrize("template", _all_templates(), ids=lambda p: p.name)
def test_no_htmx_attributes(template: Path) -> None:
    src = template.read_text()
    # `hx-` is the HTMX attribute prefix. Every attribute starts
    # with `hx-` (hx-get, hx-post, hx-target, …).
    assert " hx-" not in src and "\thx-" not in src and "\nhx-" not in src, (
        f"{template.name} reintroduced an HTMX attribute"
    )


def test_htmx_script_tag_removed_from_base() -> None:
    src = (TEMPLATE_DIR / "base.html").read_text()
    assert "htmx.org" not in src, "HTMX script tag must be removed from base.html"


@pytest.mark.parametrize(
    "token",
    [
        "--hm-surface-1",
        "--hm-surface-2",
        "--hm-surface-3",
        "--hm-foreground",
        "--hm-foreground-muted",
        "--hm-foreground-subtle",
        "--hm-accent",
        "--hm-accent-strong",
        "--hm-accent-soft",
        "--hm-success",
        "--hm-warning",
        "--hm-danger",
        "--hm-info",
        "--hm-border",
        "--hm-border-strong",
        "--hm-ring",
    ],
)
def test_semantic_token_defined(token: str) -> None:
    src = (TEMPLATE_DIR / "base.html").read_text()
    assert f"{token}:" in src, f"missing semantic token: {token}"


def test_semantic_tokens_use_oklch() -> None:
    """All tokens should be defined in OKLCH for forward-compat with
    Tailwind v4's color system."""
    src = (TEMPLATE_DIR / "base.html").read_text()
    # Find the :root block and assert every --hm-* line uses oklch().
    start = src.find(":root {")
    end = src.find("}", start)
    block = src[start:end]
    # Every line declaring a token must use oklch() — no rgb()/hex
    # fallbacks (which would defeat the v9 @theme migration).
    for line in block.splitlines():
        line = line.strip()
        if line.startswith("--hm-") and ":" in line:
            assert "oklch(" in line, (
                f"semantic token must use oklch(): {line}"
            )


def test_x_cloak_rule_centralized() -> None:
    src = (TEMPLATE_DIR / "base.html").read_text()
    assert "[x-cloak]" in src
    assert "display: none !important" in src

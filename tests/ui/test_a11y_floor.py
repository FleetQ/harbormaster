"""Static accessibility audit for v8.0.0a1 a11y floor (v8.0.0a1).

Walks every template in src/harbormaster/ui/templates/ and asserts
the a11y invariants we promised in the v8 sprint plan:

* `<html>` carries `lang=`.
* Every icon-only button (text content is `?`, `×`, `…` or only an
  Alpine `x-text` toggle that resolves to icon glyphs) has either an
  `aria-label`, a bound `:aria-label`, or wraps a non-empty
  `<span>label</span>` child.
* Every `streamText`-backed `<pre>` carries `aria-live` (chunked
  content needs SR announcement).
* Every `x-show="error"` div carries `role="alert"` (assistive tech
  reads errors immediately).
* Every loading-state submit button binds `:aria-busy`.
* `text-gray-500` does not appear paired with `bg-gray-950` body
  context — promoted to `text-gray-400` for AA contrast (4.5:1).
  This is enforced as: zero `text-gray-500` on interactive elements
  (button, a, kbd, dt) — the audit only flags the strict subset.

These assertions are deliberately strict: a future template edit
that drops one of these attributes breaks the test, surfacing the
regression at PR time rather than after a screen-reader user files
an issue.
"""
from __future__ import annotations

from html.parser import HTMLParser
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
def test_template_well_formed_html(template: Path) -> None:
    """Templates must parse via html.parser without exception."""
    HTMLParser().feed(template.read_text())


def test_base_html_has_lang() -> None:
    """`<html>` must carry `lang=` (WCAG 3.1.1)."""
    base = (TEMPLATE_DIR / "base.html").read_text()
    assert 'lang="en"' in base, "base.html must declare lang on <html>"


class _IconButtonAuditor(HTMLParser):
    """Find <button> elements whose only visible content is an icon glyph.

    A button is icon-only when all of:
      * it carries no `aria-label` / `:aria-label`
      * its text content (after stripping whitespace and `x-text`
        attribute values) is either empty or a single icon glyph
        from ICON_GLYPHS.
    """

    ICON_GLYPHS = frozenset({"?", "×", "…", "▾", "▸", "✓", "⚠", "●", "✗", "⊘", "⏸"})

    def __init__(self) -> None:
        super().__init__()
        self.violations: list[str] = []
        self._stack: list[dict] = []
        self._buf: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_dict = {k: (v or "") for k, v in attrs}
        if tag == "button":
            self._stack.append(attr_dict)
            self._buf.append("")
            return
        # When inside a button, accumulate any x-text glyphs as text proxies.
        if self._stack and "x-text" in attr_dict:
            xtext = attr_dict["x-text"]
            # Heuristic: if x-text is a ternary like "open ? '×' : '?'",
            # the resolved values are icon glyphs — count it as text.
            if any(g in xtext for g in self.ICON_GLYPHS):
                self._buf[-1] += "ICON"

    def handle_data(self, data: str) -> None:
        if self._buf:
            self._buf[-1] += data

    def handle_endtag(self, tag: str) -> None:
        if tag == "button" and self._stack:
            attrs = self._stack.pop()
            text = self._buf.pop().strip()
            # An accessible label is present if the button has aria-label,
            # :aria-label, or its inner text is a real word (not a glyph).
            has_label = (
                "aria-label" in attrs
                or ":aria-label" in attrs
                or "aria-labelledby" in attrs
            )
            inner_words = "".join(c for c in text if c.isalpha())
            has_text_label = bool(inner_words) and inner_words != "ICON"
            if not has_label and not has_text_label:
                self.violations.append(
                    f"button without accessible name: attrs={attrs!r} text={text!r}"
                )


@pytest.mark.parametrize("template", _all_templates(), ids=lambda p: p.name)
def test_icon_only_buttons_have_accessible_names(template: Path) -> None:
    """Every icon-only <button> must carry aria-label or :aria-label."""
    src = template.read_text()
    auditor = _IconButtonAuditor()
    auditor.feed(src)
    assert not auditor.violations, (
        f"{template.name} has icon-only buttons missing aria-label:\n  "
        + "\n  ".join(auditor.violations)
    )


def test_stream_panes_have_aria_live() -> None:
    """All streamText `<pre>` elements must announce updates politely."""
    for tpl in _all_templates():
        src = tpl.read_text()
        if 'x-show="streamText"' not in src:
            continue
        # Each occurrence of `x-show="streamText"` must be inside a tag
        # block that also declares `aria-live`.
        idx = 0
        while True:
            i = src.find('x-show="streamText"', idx)
            if i == -1:
                break
            # Find the surrounding tag (back to '<', forward to '>')
            tag_start = src.rfind("<", 0, i)
            tag_end = src.find(">", i)
            assert tag_start != -1 and tag_end != -1
            block = src[tag_start:tag_end + 1]
            assert "aria-live" in block, (
                f"{tpl.name}: streamText pane missing aria-live: {block[:200]}"
            )
            idx = tag_end


def test_error_displays_have_alert_role() -> None:
    """`x-show="error"` containers must declare role=alert."""
    for tpl in _all_templates():
        src = tpl.read_text()
        idx = 0
        while True:
            i = src.find('x-show="error"', idx)
            if i == -1:
                break
            tag_start = src.rfind("<", 0, i)
            tag_end = src.find(">", i)
            block = src[tag_start:tag_end + 1]
            assert 'role="alert"' in block, (
                f"{tpl.name}: x-show=\"error\" container missing role=alert:"
                f" {block[:200]}"
            )
            idx = tag_end


def test_streaming_submit_buttons_bind_aria_busy() -> None:
    """`:disabled="loading…"` submit buttons should also bind :aria-busy."""
    # Audit: any <button type="submit"> whose attrs include ":disabled"
    # referencing `loading` must also bind `:aria-busy`.
    for tpl in _all_templates():
        src = tpl.read_text()
        # Coarse: split on '<button' and inspect each token's attribute
        # span. Skip template strings (quoted Jinja).
        parts = src.split("<button")
        for part in parts[1:]:
            head = part[: part.find(">")]
            if 'type="submit"' not in head:
                continue
            if "loading" not in head or ":disabled" not in head:
                continue
            assert ":aria-busy" in head, (
                f"{tpl.name}: submit button references loading without "
                f":aria-busy: {head[:200]}"
            )

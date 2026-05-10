"""v11.0.0a3: server-side markdown rendering with bleach sanitisation.

`render_safe(md_text)` produces an HTML fragment that is safe to drop
into the memory viewer / live-preview pane. The pipeline is:

  1. Render markdown → HTML via markdown-it-py (CommonMark + GFM
     tables) — same parser the rest of the Python ecosystem relies on
     for spec-correct rendering.
  2. Sanitise the HTML with bleach using a strict allowlist of tags,
     attributes, and protocols. Anything else is stripped (NOT
     escaped) so the output stays human-readable.

Allowlist rationale:
  - Tags: standard markdown set + tables (GFM-style).
  - Attributes: `href` on `<a>`, `class` on `<code>`/`<pre>` so syntax-
    highlight class hooks survive, `align` on `<th>`/`<td>` for
    table cell alignment.
  - Protocols: `http`, `https`. Explicitly exclude `javascript`,
    `data`, `vbscript`, `file` — common XSS vectors when a memory
    file ever sources content from outside the operator's trust
    boundary.

Notes:
  - `target="_blank"` and `rel="noopener noreferrer"` are NOT auto-
    applied here; that's a UI-rendering concern. The sanitiser only
    enforces the safe attribute SET, not its values.
  - The sanitiser runs on EVERY render, including live-preview. That
    keeps the front-end logic simple — no need for a separate trusted
    path for the operator's own input.
"""
from __future__ import annotations

import bleach
from markdown_it import MarkdownIt

# Tag allowlist. Standard markdown set + tables. No raw HTML inside
# the markdown source survives — markdown-it-py's `html=False`
# default strips it before we even get to bleach.
# v12.0.0a4: extended with `<details>` + `<summary>` (collapsible
# blocks operators paste from issue templates / runbooks) and the
# footnote-link classes emitted by markdown-it footnote plugins.
_ALLOWED_TAGS: frozenset[str] = frozenset({
    "a", "p", "br", "hr",
    "strong", "em", "b", "i", "u", "s",
    "code", "pre",
    "ul", "ol", "li",
    "blockquote",
    "h1", "h2", "h3", "h4", "h5", "h6",
    "table", "thead", "tbody", "tr", "th", "td",
    "img",  # markdown ![alt](src) — sanitised by allowed_protocols
    "del",  # GFM strikethrough
    "details", "summary",  # v12.0.0a4: collapsible blocks
    "sup", "sub",  # v12.0.0a4: footnote refs use <sup><a>...</a></sup>
    "section",  # v12.0.0a4: footnote container emitted by markdown-it
})

_ALLOWED_ATTRIBUTES: dict[str, list[str]] = {
    "a": ["href", "title", "class", "id"],  # v12.0.0a4: footnote-ref / -backref classes + id targets
    "code": ["class"],
    "pre": ["class"],
    "th": ["align"],
    "td": ["align"],
    "img": ["src", "alt", "title"],
    # v12.0.0a4: footnote markup classes emitted by markdown-it.
    "li": ["id", "class"],  # footnote items have id="fn-1" + class="footnote-item"
    "section": ["class"],  # <section class="footnotes"> wrapper
    "sup": ["class"],
    "details": ["open"],
}

# Explicit allowlist — anything else (javascript:, data:, vbscript:)
# is stripped by bleach.
_ALLOWED_PROTOCOLS: list[str] = ["http", "https", "mailto"]


# Module-scope MarkdownIt instance — cheap to reuse, the parser is
# stateless across `render` calls.
_md = MarkdownIt("commonmark", {"html": False, "linkify": True}).enable(
    "table",
)


def render_safe(md_text: str) -> str:
    """Render markdown to a sanitised HTML fragment.

    Returns an empty string for an empty / non-string input — a small
    contract the live-preview endpoint can rely on without an extra
    null-check.
    """
    if not isinstance(md_text, str) or not md_text:
        return ""
    html = _md.render(md_text)
    cleaned = bleach.clean(
        html,
        tags=_ALLOWED_TAGS,
        attributes=_ALLOWED_ATTRIBUTES,
        protocols=_ALLOWED_PROTOCOLS,
        strip=True,
    )
    # bleach.clean returns Any in the type stubs — coerce for mypy.
    return str(cleaned)


__all__ = ["render_safe"]

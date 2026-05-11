"""v21.0.0a4: XSS regression suite for `/api/render-markdown`.

The memories editor (v11.0.0a3) + v12.0.0a4 extensions wired
`render_safe()` from `harbormaster.ui.markdown` to the live-preview
endpoint. This file pins the bleach allowlist behaviour against the
canonical XSS payload set so a future allowlist widening (e.g.
v15.0.0a6's `[markdown] strict = false` flag) can't accidentally let
script execution slip through.

Each test asserts on the post-sanitisation string directly rather than
the HTTP layer — `render_safe` is the single point of truth for the
sanitiser, so testing it without the FastAPI layer keeps these
regression checks fast and dependency-free.

Coverage:
  - Script tag stripped.
  - Iframe stripped.
  - `javascript:` / `data:` / `vbscript:` schemes blocked in `href`.
  - `onerror` / `onload` event handlers stripped.
  - Safe `https:` `<a>` preserved as-is.
  - v12.0.0a4 `<details><summary>` allowlist extension preserved.
"""
from __future__ import annotations

from harbormaster.ui.markdown import render_safe


# --- script + iframe -------------------------------------------------- #

def test_script_tag_stripped() -> None:
    """`<script>` tag itself must be stripped. bleach's `strip=True`
    keeps the inner text as plain text (no XSS — it's just a string)."""
    out = render_safe("<script>alert(1)</script>", strict=False)
    assert "<script" not in out.lower()
    assert "</script" not in out.lower()


def test_iframe_stripped() -> None:
    out = render_safe(
        '<iframe src="javascript:alert(1)"></iframe>', strict=False,
    )
    assert "<iframe" not in out.lower()
    assert "javascript:" not in out.lower()


# --- href protocol allowlist ----------------------------------------- #

def test_javascript_href_blocked() -> None:
    """No `<a>` with a `javascript:` href ever appears in the output.

    markdown-it-py refuses to form a link for disallowed schemes, so
    the source ends up as escaped literal text — also acceptable;
    what we care about is that no anchor with the dangerous href is
    emitted that the browser would treat as executable on click.
    """
    out = render_safe('[click](javascript:alert(1))')
    assert 'href="javascript:' not in out.lower()
    assert "<a " not in out  # no <a> at all — the link was refused


def test_data_scheme_blocked() -> None:
    """`data:` URL scheme must not become an `href`."""
    out = render_safe('[click](data:text/html,base64payload)')
    assert 'href="data:' not in out.lower()


def test_vbscript_href_blocked() -> None:
    out = render_safe('[click](vbscript:msgbox(1))')
    assert 'href="vbscript:' not in out.lower()
    assert "<a " not in out


# --- event-handler attributes ---------------------------------------- #

def test_onerror_attribute_stripped() -> None:
    out = render_safe('<img src=x onerror="alert(1)">', strict=False)
    assert "onerror" not in out.lower()
    # The <img> tag itself may survive (it's in the allowlist), but the
    # event handler must not.


def test_onload_attribute_stripped() -> None:
    out = render_safe('<svg onload="alert(1)"></svg>', strict=False)
    # <svg> is not in the allowlist; both tag and attribute must go.
    assert "onload" not in out.lower()
    assert "<svg" not in out.lower()


# --- positive: safe links + v12.0.0a4 extensions --------------------- #

def test_safe_https_link_preserved() -> None:
    out = render_safe('[safe](https://safe.example.com)')
    assert 'href="https://safe.example.com"' in out
    assert ">safe</a>" in out


def test_details_summary_preserved() -> None:
    """v12.0.0a4 allowlist extension must survive bleach."""
    out = render_safe(
        "<details><summary>title</summary>content</details>",
        strict=False,
    )
    assert "<details" in out
    assert "<summary>title</summary>" in out
    assert "content" in out

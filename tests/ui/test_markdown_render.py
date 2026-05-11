"""v11.0.0a3: server-side markdown rendering with bleach sanitisation.

Pins:
  - render_safe strips <script>, <style>, <iframe>, on* attributes.
  - href protocol allowlist: http/https/mailto pass; javascript:/data:
    are stripped.
  - Standard markdown elements survive (p, code, pre, lists, links,
    headings, tables).
  - GFM tables render as <table>.
  - Empty / non-string input returns "".
  - GET /api/projects/{name}/memories/{file}?render=html returns
    sanitised HTML with text/html content type.
  - POST /api/render-markdown returns sanitised HTML for the
    debounced live-preview path.
"""
from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from harbormaster.config import HarbormasterConfig, ProjectsConfig
from harbormaster.ui import create_app
from harbormaster.ui.markdown import render_safe


def _make_project_dir(parent: Path, name: str) -> Path:
    p = parent / name
    p.mkdir(parents=True)
    (p / ".git").mkdir()
    return p


def _config(tmp_path: Path) -> HarbormasterConfig:
    return HarbormasterConfig(
        projects=ProjectsConfig(glob=[f"{tmp_path}/*"]),
    )


# -- render_safe sanitisation -------------------------------------------


def test_render_safe_strips_script_tag() -> None:
    md = "**hi** <script>alert(1)</script>"
    out = render_safe(md)
    assert "<strong>hi</strong>" in out
    assert "<script" not in out


def test_render_safe_strips_style_tag() -> None:
    md = "<style>body{display:none}</style>text"
    out = render_safe(md)
    assert "<style" not in out
    # Inline rule blocks rendered as text or stripped — ensure no
    # functional <style> survives.
    assert "</style>" not in out


def test_render_safe_strips_iframe() -> None:
    md = '<iframe src="http://evil"></iframe>safe'
    out = render_safe(md)
    assert "<iframe" not in out
    assert "</iframe>" not in out


def test_render_safe_strips_onclick_attribute() -> None:
    # Markdown links with raw HTML attributes — markdown-it-py with
    # html=False escapes raw HTML to text (no live <a> element). The
    # defense-in-depth check: no live <a> tag with an onclick=
    # attribute survives.
    md = '<a href="http://x" onclick="alert(1)">click</a>'
    out = render_safe(md)
    # Raw HTML is escaped to entities — the angle brackets become &lt;
    # so there is no parse-able <a> tag in the output.
    assert "<a " not in out
    assert "&lt;a" in out  # escaped form survives as text


def test_render_safe_strips_javascript_protocol() -> None:
    """No <a> tag with a javascript: href ever appears in output.

    markdown-it-py's validateLink already drops unsafe URI schemes —
    the bracketed link is rendered as plain text, not as an <a>. We
    assert on the structural property: no <a href=... contains
    javascript:.
    """
    md = "[bad](javascript:alert(1))"
    out = render_safe(md)
    assert 'href="javascript:' not in out.lower()
    assert "<a " not in out  # markdown-it dropped the link entirely


def test_render_safe_strips_data_protocol() -> None:
    md = "[bad](data:text/html;base64,abc)"
    out = render_safe(md)
    assert 'href="data:' not in out.lower()


def test_render_safe_strips_vbscript_protocol() -> None:
    md = "[bad](vbscript:msgbox(1))"
    out = render_safe(md)
    assert 'href="vbscript:' not in out.lower()


def test_render_safe_allows_http_https_mailto_protocols() -> None:
    md = (
        "[a](http://example.com) "
        "[b](https://example.com) "
        "[c](mailto:x@y.com)"
    )
    out = render_safe(md)
    assert "http://example.com" in out
    assert "https://example.com" in out
    assert "mailto:x@y.com" in out


def test_render_safe_renders_basic_markdown_elements() -> None:
    md = (
        "# heading\n\n"
        "paragraph **strong** *em* `code`\n\n"
        "- a\n- b\n\n"
        "1. one\n2. two\n\n"
        "> quote\n\n"
        "```\ncodeblock\n```\n"
    )
    out = render_safe(md)
    assert "<h1>heading</h1>" in out
    assert "<strong>strong</strong>" in out
    assert "<em>em</em>" in out
    assert "<code>code</code>" in out
    assert "<ul>" in out
    assert "<ol>" in out
    assert "<blockquote>" in out
    assert "<pre>" in out


def test_render_safe_renders_gfm_tables() -> None:
    md = (
        "| h1 | h2 |\n"
        "|----|----|\n"
        "| a  | b  |\n"
    )
    out = render_safe(md)
    assert "<table>" in out
    assert "<thead>" in out
    assert "<th>h1</th>" in out
    assert "<td>a</td>" in out


def test_render_safe_empty_string_returns_empty() -> None:
    assert render_safe("") == ""


def test_render_safe_none_returns_empty() -> None:
    # mypy: ignore[arg-type] — defensive check on the runtime contract.
    assert render_safe(None) == ""  # type: ignore[arg-type]


def test_render_safe_keeps_pre_class_for_syntax_highlight() -> None:
    md = "```python\nprint(1)\n```"
    out = render_safe(md)
    # markdown-it-py emits <pre><code class="language-python">
    assert "language-python" in out


# -- Endpoint integration ----------------------------------------------


def test_get_memory_with_render_html_returns_sanitised_html(
    tmp_path: Path,
) -> None:
    p = _make_project_dir(tmp_path, "alpha")
    (p / "CLAUDE.md").write_text(
        "# header\n<script>bad</script>\n**ok**", encoding="utf-8",
    )
    client = TestClient(create_app(_config(tmp_path)))
    r = client.get("/api/projects/alpha/memories/CLAUDE.md?render=html")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")
    assert "<h1>header</h1>" in r.text
    assert "<script" not in r.text
    assert "<strong>ok</strong>" in r.text


def test_get_memory_without_render_returns_raw_markdown(
    tmp_path: Path,
) -> None:
    p = _make_project_dir(tmp_path, "alpha")
    (p / "CLAUDE.md").write_text("# header", encoding="utf-8")
    client = TestClient(create_app(_config(tmp_path)))
    r = client.get("/api/projects/alpha/memories/CLAUDE.md")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/markdown")
    assert r.text == "# header"


def test_render_markdown_endpoint(tmp_path: Path) -> None:
    client = TestClient(create_app(_config(tmp_path)))
    r = client.post(
        "/api/render-markdown",
        json={"text": "**hi** <script>x</script>"},
    )
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")
    body = r.text
    assert "<strong>hi</strong>" in body
    assert "<script" not in body


def test_render_markdown_endpoint_empty_text(tmp_path: Path) -> None:
    client = TestClient(create_app(_config(tmp_path)))
    r = client.post("/api/render-markdown", json={"text": ""})
    assert r.status_code == 200
    assert r.text == ""


def test_render_markdown_endpoint_default_text(tmp_path: Path) -> None:
    """The body field has default='' so a missing key is accepted."""
    client = TestClient(create_app(_config(tmp_path)))
    r = client.post("/api/render-markdown", json={})
    assert r.status_code == 200
    assert r.text == ""


def test_template_includes_live_preview_pane(tmp_path: Path) -> None:
    p = _make_project_dir(tmp_path, "alpha")
    (p / "CLAUDE.md").write_text("x", encoding="utf-8")
    client = TestClient(create_app(_config(tmp_path)))
    r = client.get("/projects/alpha")
    assert r.status_code == 200
    body = r.text
    # v19.0.0a6: legacy memoriesPanel "Live preview" label is now
    # "Live markdown preview" on the memoriesEditor split-pane layout;
    # the equivalent debounced render handler is `renderPreview`
    # (called from onContentChange). The endpoint contract
    # (/api/render-markdown + 300ms debounce) is unchanged.
    assert "Live markdown preview" in body
    assert "renderPreview" in body
    assert "/api/render-markdown" in body
    # Debounce hint present.
    assert "debounce.300ms" in body

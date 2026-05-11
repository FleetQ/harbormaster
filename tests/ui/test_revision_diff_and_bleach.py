"""v12.0.0a4: memory revision diff endpoint + extended bleach allowlist.

Two tightly-coupled UI memory features ship together:

  - GET /api/projects/{name}/memory-revisions/diff
      ?from=<rev_id_a>&to=<rev_id_b|optional>&file=<token>
    Returns a `text/plain; charset=utf-8` unified-diff string. When
    `to` is omitted the right-hand side is the current on-disk
    file content.

  - bleach allowlist extended with `<details>`, `<summary>`,
    `<sup>` / `<sub>` / `<section>` (footnote markup), and the
    classes/ids that markdown-it emits for footnote refs.
"""
from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from harbormaster.config import HarbormasterConfig, ProjectsConfig
from harbormaster.ui import create_app
from harbormaster.ui.markdown import render_safe
from harbormaster.ui.memory_revisions import memory_revisions


def setup_function() -> None:
    memory_revisions.clear()


def _make_project_dir(parent: Path, name: str) -> Path:
    p = parent / name
    p.mkdir(parents=True)
    (p / ".git").mkdir()
    return p


def _config(tmp_path: Path) -> HarbormasterConfig:
    return HarbormasterConfig(
        projects=ProjectsConfig(glob=[f"{tmp_path}/*"]),
    )


# -- diff endpoint ---------------------------------------------------


def test_diff_revision_to_current_returns_unified_diff(tmp_path: Path) -> None:
    """Operator's main use case: pick a revision, see what changed
    since then. Right-hand side is the current on-disk content."""
    p = _make_project_dir(tmp_path, "alpha")
    (p / "CLAUDE.md").write_text("hello world\n", encoding="utf-8")
    client = TestClient(create_app(_config(tmp_path)))

    # Save a revision via the PUT endpoint (the production write path).
    r = client.put(
        "/api/projects/alpha/memories/CLAUDE.md",
        json={"content": "hello\n"},
    )
    assert r.status_code in (200, 204)

    # Two revisions on file now: the v0 (PUT) and the file currently
    # holds whatever the PUT wrote ("hello\n"). Mutate the on-disk file
    # to differ so the diff is non-empty.
    (p / "CLAUDE.md").write_text("hello world\nfresh edit\n", encoding="utf-8")

    history = client.get(
        "/api/projects/alpha/memory-history?file=CLAUDE.md",
    ).json()
    assert history["count"] >= 1
    rev_id = history["revisions"][-1]["id"]  # earliest available

    diff = client.get(
        f"/api/projects/alpha/memory-revisions/diff?from={rev_id}&file=CLAUDE.md",
    )
    assert diff.status_code == 200
    assert diff.headers["content-type"].startswith("text/plain")
    body = diff.text
    assert body.startswith("---") or "--- revision" in body
    assert "+++ current" in body
    assert "+fresh edit" in body or "fresh edit" in body


def test_diff_two_revisions_returns_unified_diff(tmp_path: Path) -> None:
    """`from` + `to` query params diff revision A → revision B
    instead of revision A → current."""
    p = _make_project_dir(tmp_path, "alpha")
    (p / "CLAUDE.md").write_text("ignored\n", encoding="utf-8")
    client = TestClient(create_app(_config(tmp_path)))

    client.put("/api/projects/alpha/memories/CLAUDE.md", json={"content": "v1\n"})
    client.put("/api/projects/alpha/memories/CLAUDE.md", json={"content": "v2\n"})
    history = client.get(
        "/api/projects/alpha/memory-history?file=CLAUDE.md",
    ).json()
    revisions = history["revisions"]  # newest-first
    assert len(revisions) >= 2
    newer = revisions[0]["id"]
    older = revisions[1]["id"]

    diff = client.get(
        f"/api/projects/alpha/memory-revisions/diff?from={older}&to={newer}&file=CLAUDE.md",
    )
    assert diff.status_code == 200
    body = diff.text
    assert f"--- revision {older}" in body
    assert f"+++ revision {newer}" in body


def test_diff_returns_404_for_missing_from_revision(tmp_path: Path) -> None:
    p = _make_project_dir(tmp_path, "alpha")
    (p / "CLAUDE.md").write_text("hi\n", encoding="utf-8")
    client = TestClient(create_app(_config(tmp_path)))
    r = client.get(
        "/api/projects/alpha/memory-revisions/diff?from=99999&file=CLAUDE.md",
    )
    assert r.status_code == 404


def test_diff_returns_404_for_missing_to_revision(tmp_path: Path) -> None:
    p = _make_project_dir(tmp_path, "alpha")
    (p / "CLAUDE.md").write_text("hi\n", encoding="utf-8")
    client = TestClient(create_app(_config(tmp_path)))
    client.put("/api/projects/alpha/memories/CLAUDE.md", json={"content": "v1\n"})
    history = client.get(
        "/api/projects/alpha/memory-history?file=CLAUDE.md",
    ).json()
    rev_id = history["revisions"][0]["id"]
    r = client.get(
        f"/api/projects/alpha/memory-revisions/diff?from={rev_id}&to=99999&file=CLAUDE.md",
    )
    assert r.status_code == 404


def test_diff_400_when_file_is_empty(tmp_path: Path) -> None:
    p = _make_project_dir(tmp_path, "alpha")
    (p / "CLAUDE.md").write_text("hi\n", encoding="utf-8")
    client = TestClient(create_app(_config(tmp_path)))
    r = client.get("/api/projects/alpha/memory-revisions/diff?from=1&file=")
    assert r.status_code == 400


def test_diff_400_when_file_escapes_project(tmp_path: Path) -> None:
    """`?file=../etc/passwd` must not let an attacker diff against
    arbitrary files. The same defence applies to the raw revision
    endpoint via existing path validation, but diff has its own
    `target.relative_to(cwd)` check."""
    p = _make_project_dir(tmp_path, "alpha")
    (p / "CLAUDE.md").write_text("hi\n", encoding="utf-8")
    client = TestClient(create_app(_config(tmp_path)))
    client.put("/api/projects/alpha/memories/CLAUDE.md", json={"content": "v1\n"})
    history = client.get(
        "/api/projects/alpha/memory-history?file=CLAUDE.md",
    ).json()
    rev_id = history["revisions"][0]["id"]
    r = client.get(
        f"/api/projects/alpha/memory-revisions/diff?from={rev_id}&file=../../../etc/passwd",
    )
    # Either 400 (escape) or 404 (no such revision saved against that
    # path) — both block the attack. Strict check on a denial code.
    assert r.status_code in (400, 404)


def test_diff_endpoint_path_does_not_collide_with_rev_id_path(tmp_path: Path) -> None:
    """`/memory-revisions/{rev_id}` is a path with an integer; `diff`
    is a literal string. FastAPI's path resolver must route the diff
    endpoint to the diff handler, NOT try to coerce 'diff' to int and
    400 on the rev_id route."""
    p = _make_project_dir(tmp_path, "alpha")
    (p / "CLAUDE.md").write_text("hi\n", encoding="utf-8")
    client = TestClient(create_app(_config(tmp_path)))
    # No revisions saved yet → diff with from=1 returns 404, NOT 422.
    r = client.get(
        "/api/projects/alpha/memory-revisions/diff?from=1&file=CLAUDE.md",
    )
    # 404 = "from revision not found" (correct routing).
    # 422 would mean FastAPI tried to coerce "diff" to int (wrong route).
    assert r.status_code == 404


# -- extended bleach allowlist --------------------------------------


def test_bleach_allows_details_and_summary() -> None:
    """v12.0.0a4: collapsible blocks survive sanitisation."""
    # markdown-it default html=False strips raw HTML — operators get
    # the same rendering they'd get from a CommonMark parser. The
    # bleach allowlist update only matters when the rendered output
    # legitimately contains these tags (e.g. via a future plugin or
    # direct HTML injection that we WANT to allow).
    # Belt-and-braces: feed bleach.clean directly to verify the tags
    # are in the allowlist regardless of markdown-it's behaviour.
    import bleach

    from harbormaster.ui.markdown import _ALLOWED_ATTRIBUTES, _ALLOWED_TAGS

    cleaned = bleach.clean(
        '<details open><summary>x</summary>y</details>',
        tags=_ALLOWED_TAGS, attributes=_ALLOWED_ATTRIBUTES, strip=True,
    )
    assert "<details" in cleaned
    assert "<summary>" in cleaned
    assert "open" in cleaned  # open attr survives


def test_bleach_allows_footnote_markup_classes() -> None:
    """Footnote refs (markdown-it emits) carry footnote-ref + footnote-
    backref class names. The allowlist update routes them through."""
    import bleach

    from harbormaster.ui.markdown import _ALLOWED_ATTRIBUTES, _ALLOWED_TAGS

    cleaned = bleach.clean(
        '<sup class="footnote-ref"><a href="#fn-1" class="footnote-link" '
        'id="fnref-1">[1]</a></sup>',
        tags=_ALLOWED_TAGS, attributes=_ALLOWED_ATTRIBUTES, strip=True,
    )
    assert "<sup" in cleaned
    assert 'class="footnote-ref"' in cleaned
    assert 'id="fnref-1"' in cleaned
    assert 'class="footnote-link"' in cleaned


def test_bleach_allows_footnote_section() -> None:
    """The `<section class="footnotes">` wrapper at the bottom of a
    document with footnotes."""
    import bleach

    from harbormaster.ui.markdown import _ALLOWED_ATTRIBUTES, _ALLOWED_TAGS

    cleaned = bleach.clean(
        '<section class="footnotes"><ol><li id="fn-1" class="footnote-item">'
        'note</li></ol></section>',
        tags=_ALLOWED_TAGS, attributes=_ALLOWED_ATTRIBUTES, strip=True,
    )
    assert "<section" in cleaned
    assert 'class="footnotes"' in cleaned
    assert 'id="fn-1"' in cleaned


def test_bleach_still_strips_dangerous_tags() -> None:
    """The new tags don't open a hole — `<script>`, `<iframe>`,
    `<object>` are still stripped."""
    out = render_safe("ok <script>alert(1)</script> done")
    assert "<script" not in out
    assert "alert(1)" not in out or "&lt;" in out  # text-content escaped


def test_bleach_javascript_protocol_still_stripped() -> None:
    """No anchor element with a javascript: href should ever survive
    sanitisation. The literal text may appear (it's a markdown link
    that markdown-it didn't recognise as a valid URL), but it must
    NOT be rendered as a clickable anchor."""
    out = render_safe("[click](javascript:alert(1))")
    assert '<a href="javascript:' not in out
    assert "<a href='javascript:" not in out
    # And feeding bleach a raw <a> with javascript: href strips the href.
    import bleach

    from harbormaster.ui.markdown import _ALLOWED_ATTRIBUTES, _ALLOWED_PROTOCOLS, _ALLOWED_TAGS
    cleaned = bleach.clean(
        '<a href="javascript:alert(1)">x</a>',
        tags=_ALLOWED_TAGS, attributes=_ALLOWED_ATTRIBUTES,
        protocols=_ALLOWED_PROTOCOLS, strip=True,
    )
    assert "javascript:" not in cleaned


# -- UI dropdown wiring --------------------------------------------


def test_diff_dropdown_present_in_memory_editor(tmp_path: Path) -> None:
    """v19.0.0a6: the legacy memoriesPanel `diffFrom` state var was
    renamed to `diffAgainst` on the new memoriesEditor, but the dropdown
    contract (aria-label + loadDiff handler) is preserved."""
    p = _make_project_dir(tmp_path, "alpha")
    (p / "CLAUDE.md").write_text("hi\n", encoding="utf-8")
    client = TestClient(create_app(_config(tmp_path)))
    body = client.get("/projects/alpha").text
    assert "diffAgainst" in body
    assert 'aria-label="Diff against revision"' in body
    assert "loadDiff()" in body


def test_loaddiff_calls_diff_endpoint_with_query_params(tmp_path: Path) -> None:
    """The Alpine factory's loadDiff() builds the right URL — guard
    against drift between the Python endpoint signature and the JS
    caller. v19.0.0a6: the new editor puts `?file=` first (then `&from=`
    and `&format=html`) — the FastAPI route accepts query params in any
    order so both shapes hit the same handler."""
    p = _make_project_dir(tmp_path, "alpha")
    (p / "CLAUDE.md").write_text("hi\n", encoding="utf-8")
    client = TestClient(create_app(_config(tmp_path)))
    body = client.get("/projects/alpha").text
    assert "/memory-revisions/diff`" in body
    assert "?file=" in body
    assert "&from=" in body


def test_select_resets_diff_state(tmp_path: Path) -> None:
    """v19.0.0a6: the legacy memoriesPanel toggleHistory() reset the
    diff state when closing the history panel; the new memoriesEditor
    has no separate history-panel toggle, so the equivalent guarantee
    is provided by select(): switching files resets diffAgainst +
    diffHtml so the new file starts with a clean diff slate."""
    p = _make_project_dir(tmp_path, "alpha")
    (p / "CLAUDE.md").write_text("hi\n", encoding="utf-8")
    client = TestClient(create_app(_config(tmp_path)))
    body = client.get("/projects/alpha").text
    assert "this.diffAgainst = ''" in body
    assert "this.diffHtml = ''" in body

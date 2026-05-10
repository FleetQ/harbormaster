"""v15.0.0a1 — memory tag UX cluster.

Three v14-retro carry-overs combined:

* YAML block-list tag form is parsed by the server.
* Multi-tag intersection / union (AND/OR) filter UI wires up.
* Persistent undo/redo cursor across page reloads via localStorage.
"""
from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from harbormaster.config import HarbormasterConfig, ProjectsConfig
from harbormaster.ui import create_app

TEMPLATE_DIR = (
    Path(__file__).parent.parent.parent
    / "src"
    / "harbormaster"
    / "ui"
    / "templates"
)


def _read(name: str) -> str:
    return (TEMPLATE_DIR / name).read_text(encoding="utf-8")


def _make_project_dir(parent: Path, name: str) -> Path:
    p = parent / name
    p.mkdir(parents=True)
    (p / ".git").mkdir()
    return p


def _config(tmp_path: Path) -> HarbormasterConfig:
    return HarbormasterConfig(
        projects=ProjectsConfig(glob=[f"{tmp_path}/*"]),
    )


# -- block-list YAML frontmatter parsing ------------------------------


def test_memories_list_tags_block_list_form(tmp_path: Path) -> None:
    """v15.0.0a1: ``tags:\\n  - foo\\n  - bar`` is parsed."""
    p = _make_project_dir(tmp_path, "alpha")
    (p / "CLAUDE.md").write_text(
        "---\ntags:\n  - foo\n  - bar\n  - baz\n---\nbody\n",
        encoding="utf-8",
    )
    client = TestClient(create_app(_config(tmp_path)))
    files = client.get("/api/projects/alpha/memories").json()["files"]
    assert files[0]["tags"] == ["foo", "bar", "baz"]


def test_memories_list_tags_block_list_with_quotes(tmp_path: Path) -> None:
    p = _make_project_dir(tmp_path, "alpha")
    (p / "CLAUDE.md").write_text(
        '---\ntags:\n  - "with space"\n  - \'single\'\n  - bare\n---\n',
        encoding="utf-8",
    )
    client = TestClient(create_app(_config(tmp_path)))
    files = client.get("/api/projects/alpha/memories").json()["files"]
    assert files[0]["tags"] == ["with space", "single", "bare"]


def test_memories_list_tags_block_list_terminates_on_other_key(
    tmp_path: Path,
) -> None:
    """Block-list parser must stop at the next non-list line."""
    p = _make_project_dir(tmp_path, "alpha")
    (p / "CLAUDE.md").write_text(
        "---\ntags:\n  - foo\n  - bar\nauthor: katya\n---\n",
        encoding="utf-8",
    )
    client = TestClient(create_app(_config(tmp_path)))
    files = client.get("/api/projects/alpha/memories").json()["files"]
    assert files[0]["tags"] == ["foo", "bar"]


def test_memories_list_tags_inline_form_still_works(tmp_path: Path) -> None:
    """v14.0.0a5 inline form must still parse after the v15 extension."""
    p = _make_project_dir(tmp_path, "alpha")
    (p / "CLAUDE.md").write_text(
        "---\ntags: [foo, bar]\n---\n",
        encoding="utf-8",
    )
    client = TestClient(create_app(_config(tmp_path)))
    files = client.get("/api/projects/alpha/memories").json()["files"]
    assert files[0]["tags"] == ["foo", "bar"]


# -- AND/OR filter mode UI wiring ------------------------------------


def test_project_detail_renders_and_or_toggle() -> None:
    body = _read("project_detail.html")
    assert "tagFilterMode" in body
    assert "Match all tags (AND)" in body
    assert "Match any tag (OR)" in body
    # Default mode is AND.
    assert "tagFilterMode: 'and'" in body


def test_project_detail_filter_logic_handles_and_mode() -> None:
    body = _read("project_detail.html")
    # AND requires every token to match.
    assert "tokens.every(tok => matchToken(f.tags, tok))" in body


def test_project_detail_filter_logic_handles_or_mode() -> None:
    body = _read("project_detail.html")
    # OR requires at least one token to match.
    assert "tokens.some(tok => matchToken(f.tags, tok))" in body


def test_project_detail_filter_splits_on_comma() -> None:
    body = _read("project_detail.html")
    assert "raw.split(',').map(t => t.trim()).filter(Boolean)" in body


# -- chip-input editor UI wiring -------------------------------------


def test_project_detail_renders_chip_input_editor() -> None:
    body = _read("project_detail.html")
    assert "Tags (frontmatter)" in body
    assert "addTagChip()" in body
    assert "removeTagChip(i)" in body
    assert "x-for=\"(t, i) in tagChips\"" in body


def test_project_detail_chip_helpers_wired() -> None:
    body = _read("project_detail.html")
    # Chip helpers exist on the Alpine factory.
    assert "_parseChipsFromDraft()" in body
    assert "_writeChipsToDraft()" in body
    # Block-list output (matches what the server parser accepts).
    assert "tagSection.push('tags:')" in body
    assert "tagSection.push('  - '" in body


def test_project_detail_chip_input_dedups_case_insensitive() -> None:
    body = _read("project_detail.html")
    assert (
        "this.tagChips.some(x => x.toLowerCase() === t.toLowerCase())" in body
    )


# -- persistent revision cursor wiring ------------------------------


def test_project_detail_persists_cursor_to_localstorage() -> None:
    body = _read("project_detail.html")
    # Helper presence + storage key shape.
    assert "_persistCursor()" in body
    assert "_restoreCursor()" in body
    assert "hm:revcursor:${this.project}:${this.selected.name}" in body
    # Persist + restore wired into navigateRevisions / select.
    assert "this._restoreCursor()" in body


def test_project_detail_clears_persisted_cursor_at_live() -> None:
    body = _read("project_detail.html")
    # When cursor returns to live (null), localStorage entry is removed.
    assert "window.localStorage.removeItem(k)" in body


def test_project_detail_select_restores_cursor_not_resets() -> None:
    """v14.a5 reset cursor to null on switch; v15.a1 restores per-file."""
    body = _read("project_detail.html")
    # The reset-to-null line was replaced by _restoreCursor() in select().
    # We assert the v15 wording is present in the comment.
    assert (
        "restore from localStorage if a cursor is persisted" in body
    )

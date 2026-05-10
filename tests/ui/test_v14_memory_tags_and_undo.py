"""v14.0.0a5 — memory tag parsing + UI wiring for tagging + undo/redo."""
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


# -- frontmatter tag parsing ------------------------------------------


def test_memories_list_includes_tags_for_files_with_frontmatter(
    tmp_path: Path,
) -> None:
    p = _make_project_dir(tmp_path, "alpha")
    (p / "CLAUDE.md").write_text(
        "---\ntags: [foo, bar, baz]\n---\n\nbody\n",
        encoding="utf-8",
    )
    client = TestClient(create_app(_config(tmp_path)))
    r = client.get("/api/projects/alpha/memories")
    assert r.status_code == 200
    files = r.json()["files"]
    by_name = {f["name"]: f for f in files}
    assert by_name["CLAUDE.md"]["tags"] == ["foo", "bar", "baz"]


def test_memories_list_tags_default_empty_when_no_frontmatter(
    tmp_path: Path,
) -> None:
    p = _make_project_dir(tmp_path, "alpha")
    (p / "CLAUDE.md").write_text("plain body\n", encoding="utf-8")
    client = TestClient(create_app(_config(tmp_path)))
    files = client.get("/api/projects/alpha/memories").json()["files"]
    assert files[0]["tags"] == []


def test_memories_list_tags_quoted_strings(tmp_path: Path) -> None:
    p = _make_project_dir(tmp_path, "alpha")
    (p / "CLAUDE.md").write_text(
        '---\ntags: ["with space", \'single-quoted\', plain]\n---\n',
        encoding="utf-8",
    )
    client = TestClient(create_app(_config(tmp_path)))
    files = client.get("/api/projects/alpha/memories").json()["files"]
    assert files[0]["tags"] == ["with space", "single-quoted", "plain"]


def test_memories_list_tags_malformed_frontmatter_returns_empty(
    tmp_path: Path,
) -> None:
    """Garbage frontmatter must NOT crash the listing — silent fallback."""
    p = _make_project_dir(tmp_path, "alpha")
    (p / "CLAUDE.md").write_text(
        "---\ntags: not-a-list\n---\nbody\n",
        encoding="utf-8",
    )
    client = TestClient(create_app(_config(tmp_path)))
    r = client.get("/api/projects/alpha/memories")
    assert r.status_code == 200
    assert r.json()["files"][0]["tags"] == []


def test_memories_list_tags_serena_subdir_files(tmp_path: Path) -> None:
    p = _make_project_dir(tmp_path, "alpha")
    serena = p / ".serena" / "memories"
    serena.mkdir(parents=True)
    (serena / "arch.md").write_text(
        "---\ntags: [arch, ddd]\n---\n",
        encoding="utf-8",
    )
    client = TestClient(create_app(_config(tmp_path)))
    files = client.get("/api/projects/alpha/memories").json()["files"]
    by_name = {f["name"]: f for f in files}
    assert by_name[".serena/memories/arch.md"]["tags"] == ["arch", "ddd"]


def test_memories_list_tags_only_reads_first_4kb(tmp_path: Path) -> None:
    """Frontmatter beyond the first 4 KiB must NOT be picked up."""
    p = _make_project_dir(tmp_path, "alpha")
    # Write 8 KiB of body BEFORE the frontmatter — outside the read budget.
    body = "x" * 8192 + "\n---\ntags: [late]\n---\n"
    (p / "CLAUDE.md").write_text(body, encoding="utf-8")
    client = TestClient(create_app(_config(tmp_path)))
    files = client.get("/api/projects/alpha/memories").json()["files"]
    # Frontmatter doesn't open at byte 0, so no tags found.
    assert files[0]["tags"] == []


# -- UI wiring (template smoke) ---------------------------------------


def test_project_detail_has_tag_filter_input() -> None:
    body = _read("project_detail.html")
    assert "Filter memories by tag" in body
    assert "filteredFiles()" in body
    assert "tagFilter" in body


def test_project_detail_renders_tag_pills() -> None:
    body = _read("project_detail.html")
    # Tag pills loop with the cyan-pill class.
    assert "x-for=\"t in (f.tags || [])\"" in body
    assert "bg-cyan-900/40 text-accent" in body


def test_project_detail_filtered_files_handles_empty_filter() -> None:
    body = _read("project_detail.html")
    # Empty filter must early-return the unfiltered files array.
    assert "if (!q) return this.files" in body


def test_project_detail_textarea_binds_undo_redo_keys() -> None:
    body = _read("project_detail.html")
    # All four keychord variants — Cmd / Ctrl × Z / Shift+Z.
    assert "@keydown.meta.z.prevent" in body
    assert "@keydown.ctrl.z.prevent" in body
    assert "@keydown.meta.shift.z.prevent" in body
    assert "@keydown.ctrl.shift.z.prevent" in body
    assert "navigateRevisions(-1)" in body
    assert "navigateRevisions(1)" in body


def test_project_detail_navigate_revisions_returns_to_live_at_cursor_zero() -> None:
    """Cmd+Shift+Z from cursor=0 → null (live). The cycle:
    null → 0 → 1 → ...     (Cmd+Z, older)
    ... 1 → 0 → null       (Cmd+Shift+Z, newer)"""
    body = _read("project_detail.html")
    # The branch that resets the cursor + refetches the live file.
    assert "this.revisionCursor = null" in body
    assert "Restore the live (on-disk) draft" in body


def test_project_detail_revision_cursor_state_initialised_null() -> None:
    body = _read("project_detail.html")
    assert "revisionCursor: null" in body


def test_project_detail_undo_redo_status_line_renders() -> None:
    """The 'position' indicator under the textarea is gated on
    `editing && revisions.length > 0`, and shows either 'live' or
    `#N of M`."""
    body = _read("project_detail.html")
    assert 'editing && (revisions.length > 0)' in body
    assert "revisionCursor === null ? 'live'" in body

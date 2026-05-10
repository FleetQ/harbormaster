"""v10.0.0a5: per-project memories viewer (read-only).

Pins:
  - GET /api/projects/{name}/memories — lists CLAUDE.md and
    .serena/memories/*.md with size + mtime.
  - GET /api/projects/{name}/memories/{file} — returns raw markdown.
  - Path-traversal protections (400 on bad file token).
  - 404 on unknown project / missing file.
  - Sidebar template wires a script tag for vendored marked.min.js.
"""
from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from harbormaster.config import HarbormasterConfig, ProjectsConfig
from harbormaster.ui import create_app


def _make_project_dir(parent: Path, name: str) -> Path:
    p = parent / name
    p.mkdir(parents=True)
    (p / ".git").mkdir()
    return p


def _config(tmp_path: Path) -> HarbormasterConfig:
    return HarbormasterConfig(
        projects=ProjectsConfig(glob=[f"{tmp_path}/*"]),
    )


def test_list_memories_empty_when_no_files(tmp_path: Path) -> None:
    p = _make_project_dir(tmp_path, "alpha")
    assert p.is_dir()
    client = TestClient(create_app(_config(tmp_path)))
    r = client.get("/api/projects/alpha/memories")
    assert r.status_code == 200
    body = r.json()
    assert body["project"] == "alpha"
    assert body["files"] == []


def test_list_memories_returns_claude_md_and_serena(tmp_path: Path) -> None:
    p = _make_project_dir(tmp_path, "alpha")
    (p / "CLAUDE.md").write_text("# Hello\nbody", encoding="utf-8")
    serena = p / ".serena" / "memories"
    serena.mkdir(parents=True)
    (serena / "architecture.md").write_text("arch notes", encoding="utf-8")
    (serena / "conventions.md").write_text("conv", encoding="utf-8")
    # Non-md file should NOT be listed.
    (serena / "junk.txt").write_text("not md", encoding="utf-8")

    client = TestClient(create_app(_config(tmp_path)))
    body = client.get("/api/projects/alpha/memories").json()
    names = sorted(f["name"] for f in body["files"])
    assert names == [
        ".serena/memories/architecture.md",
        ".serena/memories/conventions.md",
        "CLAUDE.md",
    ]
    # Each entry has size + mtime.
    for f in body["files"]:
        assert isinstance(f["size"], int) and f["size"] > 0
        assert isinstance(f["mtime"], int) and f["mtime"] > 0


def test_get_memory_returns_raw_markdown(tmp_path: Path) -> None:
    p = _make_project_dir(tmp_path, "alpha")
    (p / "CLAUDE.md").write_text("# Title\nBody text", encoding="utf-8")
    client = TestClient(create_app(_config(tmp_path)))
    r = client.get("/api/projects/alpha/memories/CLAUDE.md")
    assert r.status_code == 200
    assert r.text == "# Title\nBody text"
    assert r.headers["content-type"].startswith("text/markdown")


def test_get_serena_memory(tmp_path: Path) -> None:
    p = _make_project_dir(tmp_path, "alpha")
    serena = p / ".serena" / "memories"
    serena.mkdir(parents=True)
    (serena / "arch.md").write_text("architecture", encoding="utf-8")
    client = TestClient(create_app(_config(tmp_path)))
    r = client.get("/api/projects/alpha/memories/.serena/memories/arch.md")
    assert r.status_code == 200
    assert r.text == "architecture"


def test_get_unknown_project_returns_404(tmp_path: Path) -> None:
    client = TestClient(create_app(_config(tmp_path)))
    r = client.get("/api/projects/missing/memories")
    assert r.status_code == 404


def test_get_missing_memory_returns_404(tmp_path: Path) -> None:
    _make_project_dir(tmp_path, "alpha")
    client = TestClient(create_app(_config(tmp_path)))
    r = client.get("/api/projects/alpha/memories/CLAUDE.md")
    assert r.status_code == 404


def test_path_traversal_dotdot_returns_400(tmp_path: Path) -> None:
    _make_project_dir(tmp_path, "alpha")
    client = TestClient(create_app(_config(tmp_path)))
    r = client.get("/api/projects/alpha/memories/..%2Fsecret.md")
    assert r.status_code == 400


def test_disallowed_filename_returns_400(tmp_path: Path) -> None:
    """Anything outside CLAUDE.md or .serena/memories/*.md must 400."""
    p = _make_project_dir(tmp_path, "alpha")
    (p / "secret.md").write_text("nope", encoding="utf-8")
    client = TestClient(create_app(_config(tmp_path)))
    # secret.md is at the project root but NOT CLAUDE.md → 400.
    r = client.get("/api/projects/alpha/memories/secret.md")
    assert r.status_code == 400


def test_serena_subdir_filename_must_be_clean_basename(tmp_path: Path) -> None:
    """`.serena/memories/sub/dir.md` must 400 (no nested slashes
    inside the basename)."""
    _make_project_dir(tmp_path, "alpha")
    client = TestClient(create_app(_config(tmp_path)))
    r = client.get("/api/projects/alpha/memories/.serena/memories/sub/dir.md")
    assert r.status_code == 400


def test_invalid_project_name_returns_400(tmp_path: Path) -> None:
    client = TestClient(create_app(_config(tmp_path)))
    r = client.get("/api/projects/..%2Fevil/memories")
    # The project-name validator returns 400 (or the route fails to
    # match — 404 is also acceptable here).
    assert r.status_code in (400, 404)


def test_project_detail_template_includes_marked_vendor() -> None:
    src = (
        Path(__file__).parent.parent.parent
        / "src" / "harbormaster" / "ui"
        / "templates" / "project_detail.html"
    ).read_text()
    assert "/static/vendor/marked.min.js" in src
    assert "memoriesPanel" in src


def test_marked_vendor_file_present() -> None:
    """Sentinel: the vendored marked.min.js must be on disk so it
    ships with the wheel."""
    p = (
        Path(__file__).parent.parent.parent
        / "src" / "harbormaster" / "ui"
        / "static" / "vendor" / "marked.min.js"
    )
    assert p.is_file()
    body = p.read_text()
    assert "marked" in body[:200].lower()


def test_marked_vendor_served_via_static_route(tmp_path: Path) -> None:
    client = TestClient(create_app(_config(tmp_path)))
    r = client.get("/static/vendor/marked.min.js")
    assert r.status_code == 200
    assert "javascript" in r.headers["content-type"]

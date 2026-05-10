"""v10.0.0a6: per-project memories editor (write-back).

Pins:
  - PUT /api/projects/{name}/memories/{file} updates an existing
    file atomically (temp + rename).
  - POST /api/projects/{name}/memories creates a new file in the
    allowlist (CLAUDE.md or .serena/memories/<name>.md).
  - Path-traversal protections from a5 still apply.
  - 409 on POST when the file already exists.
  - 400 on bad filename token.
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


def test_put_updates_existing_claude_md(tmp_path: Path) -> None:
    p = _make_project_dir(tmp_path, "alpha")
    (p / "CLAUDE.md").write_text("old", encoding="utf-8")
    client = TestClient(create_app(_config(tmp_path)))
    r = client.put(
        "/api/projects/alpha/memories/CLAUDE.md",
        json={"content": "new content here"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["created"] is False
    assert body["size"] == len("new content here")
    assert (p / "CLAUDE.md").read_text() == "new content here"


def test_put_creates_when_target_missing(tmp_path: Path) -> None:
    """PUT is upsert — creating CLAUDE.md if it doesn't exist."""
    p = _make_project_dir(tmp_path, "alpha")
    assert not (p / "CLAUDE.md").exists()
    client = TestClient(create_app(_config(tmp_path)))
    r = client.put(
        "/api/projects/alpha/memories/CLAUDE.md",
        json={"content": "fresh"},
    )
    assert r.status_code == 200
    assert (p / "CLAUDE.md").read_text() == "fresh"


def test_post_creates_new_serena_memory(tmp_path: Path) -> None:
    p = _make_project_dir(tmp_path, "alpha")
    client = TestClient(create_app(_config(tmp_path)))
    r = client.post(
        "/api/projects/alpha/memories",
        json={
            "filename": ".serena/memories/architecture.md",
            "content": "# Arch\nbody",
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["created"] is True
    assert body["file"] == ".serena/memories/architecture.md"
    target = p / ".serena" / "memories" / "architecture.md"
    assert target.is_file()
    assert target.read_text() == "# Arch\nbody"


def test_post_creates_claude_md(tmp_path: Path) -> None:
    p = _make_project_dir(tmp_path, "alpha")
    client = TestClient(create_app(_config(tmp_path)))
    r = client.post(
        "/api/projects/alpha/memories",
        json={"filename": "CLAUDE.md", "content": "hi"},
    )
    assert r.status_code == 200
    assert (p / "CLAUDE.md").read_text() == "hi"


def test_post_returns_409_when_file_exists(tmp_path: Path) -> None:
    p = _make_project_dir(tmp_path, "alpha")
    (p / "CLAUDE.md").write_text("already there", encoding="utf-8")
    client = TestClient(create_app(_config(tmp_path)))
    r = client.post(
        "/api/projects/alpha/memories",
        json={"filename": "CLAUDE.md", "content": "new"},
    )
    assert r.status_code == 409


def test_put_path_traversal_returns_400(tmp_path: Path) -> None:
    _make_project_dir(tmp_path, "alpha")
    client = TestClient(create_app(_config(tmp_path)))
    r = client.put(
        "/api/projects/alpha/memories/..%2Fsecret.md",
        json={"content": "owned"},
    )
    assert r.status_code == 400


def test_post_disallowed_filename_returns_400(tmp_path: Path) -> None:
    """POST with a filename outside the allowlist must 400."""
    _make_project_dir(tmp_path, "alpha")
    client = TestClient(create_app(_config(tmp_path)))
    r = client.post(
        "/api/projects/alpha/memories",
        json={"filename": "secret.md", "content": "no"},
    )
    assert r.status_code == 400


def test_post_creates_serena_memories_dir_if_missing(tmp_path: Path) -> None:
    """The `.serena/memories` directory may not exist yet — POST
    must mkdir it via the atomic write helper."""
    p = _make_project_dir(tmp_path, "alpha")
    assert not (p / ".serena").exists()
    client = TestClient(create_app(_config(tmp_path)))
    r = client.post(
        "/api/projects/alpha/memories",
        json={
            "filename": ".serena/memories/notes.md",
            "content": "first note",
        },
    )
    assert r.status_code == 200
    assert (p / ".serena" / "memories" / "notes.md").read_text() == "first note"


def test_put_unknown_project_returns_404(tmp_path: Path) -> None:
    client = TestClient(create_app(_config(tmp_path)))
    r = client.put(
        "/api/projects/missing/memories/CLAUDE.md",
        json={"content": "x"},
    )
    assert r.status_code == 404


def test_put_writes_atomically_no_partial_file(tmp_path: Path) -> None:
    """The temp file used by atomic_write must be cleaned up after
    a successful rename."""
    p = _make_project_dir(tmp_path, "alpha")
    (p / "CLAUDE.md").write_text("old", encoding="utf-8")
    client = TestClient(create_app(_config(tmp_path)))
    client.put(
        "/api/projects/alpha/memories/CLAUDE.md",
        json={"content": "new"},
    )
    # No `.hm-tmp` leftover.
    leftover = list(p.glob("*.hm-tmp"))
    assert leftover == []


def test_template_includes_editor_controls() -> None:
    """The Alpine memoriesPanel must wire the edit / save / new-memory
    handlers so the read-only viewer from a5 has working write surfaces."""
    src = (
        Path(__file__).parent.parent.parent
        / "src" / "harbormaster" / "ui"
        / "templates" / "project_detail.html"
    ).read_text()
    assert "startEdit()" in src
    assert "save()" in src
    assert "createNew()" in src
    assert "creating: false" in src

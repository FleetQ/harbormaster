"""v11.0.0a2: Memory revision history.

Pins:
  - PUT /api/projects/{name}/memories/{file} appends a revision row.
  - POST /api/projects/{name}/memories appends a revision row on create.
  - GET /api/projects/{name}/memory-history?file=<token> returns
    descending list of revisions (id + saved_at + bytes_diff).
  - GET /api/projects/{name}/memory-revisions/{rev_id}?file=<token>
    returns the persisted content as text/markdown.
  - 404 when revision id is unknown.
  - Per-(project, file) cap is honoured (default 20).
  - bytes_diff: None on first revision, signed delta thereafter.
  - DB file mode is 0600.
  - Revision writeback never breaks the memory write itself.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient

from harbormaster.config import HarbormasterConfig, ProjectsConfig
from harbormaster.ui import create_app
from harbormaster.ui.memory_revisions import (
    MAX_REVISIONS_PER_FILE,
    MemoryRevisionsStore,
    memory_revisions,
)


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


# -- Store mechanics ---------------------------------------------------


def test_store_record_first_revision_has_no_bytes_diff(tmp_path: Path) -> None:
    store = MemoryRevisionsStore(db_path=tmp_path / "rev.db")
    rev_id = store.record(
        project="alpha", file="CLAUDE.md",
        content="hello", saved_at=100,
    )
    assert rev_id > 0
    history = store.history(project="alpha", file="CLAUDE.md")
    assert len(history) == 1
    assert history[0].bytes_diff is None
    assert history[0].saved_at == 100


def test_store_subsequent_revisions_have_signed_bytes_diff(
    tmp_path: Path,
) -> None:
    store = MemoryRevisionsStore(db_path=tmp_path / "rev.db")
    store.record(project="alpha", file="CLAUDE.md", content="ab", saved_at=1)
    store.record(project="alpha", file="CLAUDE.md", content="abcde", saved_at=2)
    store.record(project="alpha", file="CLAUDE.md", content="x", saved_at=3)

    history = store.history(project="alpha", file="CLAUDE.md")
    # Newest first.
    assert [r.saved_at for r in history] == [3, 2, 1]
    assert history[0].bytes_diff == 1 - 5   # "x" vs "abcde"
    assert history[1].bytes_diff == 5 - 2   # "abcde" vs "ab"
    assert history[2].bytes_diff is None     # first ever


def test_store_get_revision_returns_content(tmp_path: Path) -> None:
    store = MemoryRevisionsStore(db_path=tmp_path / "rev.db")
    rev_id = store.record(
        project="alpha", file="CLAUDE.md",
        content="payload", saved_at=42,
    )
    got = store.get_revision(project="alpha", file="CLAUDE.md", rev_id=rev_id)
    assert got is not None
    assert got.content == "payload"
    assert got.saved_at == 42


def test_store_get_revision_not_found_returns_none(tmp_path: Path) -> None:
    store = MemoryRevisionsStore(db_path=tmp_path / "rev.db")
    assert store.get_revision(project="x", file="y", rev_id=9999) is None


def test_store_history_isolates_per_project_file(tmp_path: Path) -> None:
    store = MemoryRevisionsStore(db_path=tmp_path / "rev.db")
    store.record(project="alpha", file="CLAUDE.md", content="A", saved_at=1)
    store.record(project="beta", file="CLAUDE.md", content="B", saved_at=2)
    store.record(
        project="alpha", file=".serena/memories/x.md",
        content="C", saved_at=3,
    )
    assert len(store.history("alpha", "CLAUDE.md")) == 1
    assert len(store.history("beta", "CLAUDE.md")) == 1
    assert len(store.history("alpha", ".serena/memories/x.md")) == 1


def test_store_prunes_to_max_per_file(tmp_path: Path) -> None:
    store = MemoryRevisionsStore(db_path=tmp_path / "rev.db", max_per_file=3)
    for i in range(7):
        store.record(
            project="alpha", file="CLAUDE.md",
            content=f"v{i}", saved_at=i,
        )
    history = store.history(project="alpha", file="CLAUDE.md")
    assert len(history) == 3
    # Newest 3 retained; oldest pruned.
    assert [r.saved_at for r in history] == [6, 5, 4]


def test_store_db_file_has_0600_mode(tmp_path: Path) -> None:
    db = tmp_path / "rev.db"
    MemoryRevisionsStore(db_path=db)
    mode = db.stat().st_mode & 0o777
    assert mode == 0o600


def test_store_clear_truncates_table(tmp_path: Path) -> None:
    store = MemoryRevisionsStore(db_path=tmp_path / "rev.db")
    store.record(project="a", file="b", content="c", saved_at=1)
    assert len(store.history("a", "b")) == 1
    store.clear()
    assert store.history("a", "b") == []


def test_store_persists_across_reopen(tmp_path: Path) -> None:
    db = tmp_path / "rev.db"
    s1 = MemoryRevisionsStore(db_path=db)
    s1.record(project="a", file="b", content="c", saved_at=1)
    s1.close()
    s2 = MemoryRevisionsStore(db_path=db)
    assert len(s2.history("a", "b")) == 1


def test_store_db_schema_matches_spec(tmp_path: Path) -> None:
    db = tmp_path / "rev.db"
    MemoryRevisionsStore(db_path=db)
    conn = sqlite3.connect(str(db))
    cols = [
        (row[1], row[2])
        for row in conn.execute("PRAGMA table_info(memory_revisions)")
    ]
    conn.close()
    assert cols == [
        ("id", "INTEGER"),
        ("project", "TEXT"),
        ("file", "TEXT"),
        ("saved_at", "INTEGER"),
        ("content", "TEXT"),
        ("bytes_diff", "INTEGER"),
    ]


def test_max_revisions_default_is_20() -> None:
    """Spec pin: default cap is 20 revisions per (project, file)."""
    assert MAX_REVISIONS_PER_FILE == 20


# -- Endpoint integration ---------------------------------------------


def test_put_records_revision(tmp_path: Path) -> None:
    p = _make_project_dir(tmp_path, "alpha")
    (p / "CLAUDE.md").write_text("old", encoding="utf-8")
    client = TestClient(create_app(_config(tmp_path)))

    r = client.put(
        "/api/projects/alpha/memories/CLAUDE.md",
        json={"content": "new content"},
    )
    assert r.status_code == 200

    history = memory_revisions.history(project="alpha", file="CLAUDE.md")
    assert len(history) == 1
    rev = memory_revisions.get_revision(
        project="alpha", file="CLAUDE.md", rev_id=history[0].id,
    )
    assert rev is not None
    assert rev.content == "new content"


def test_post_records_revision(tmp_path: Path) -> None:
    p = _make_project_dir(tmp_path, "alpha")
    (p / ".serena").mkdir()
    (p / ".serena" / "memories").mkdir()
    client = TestClient(create_app(_config(tmp_path)))

    r = client.post(
        "/api/projects/alpha/memories",
        json={
            "filename": ".serena/memories/note.md",
            "content": "# Note\nbody",
        },
    )
    assert r.status_code == 200
    history = memory_revisions.history(
        project="alpha", file=".serena/memories/note.md",
    )
    assert len(history) == 1
    assert history[0].bytes_diff is None  # first revision


def test_get_memory_history_endpoint(tmp_path: Path) -> None:
    p = _make_project_dir(tmp_path, "alpha")
    (p / "CLAUDE.md").write_text("v0", encoding="utf-8")
    client = TestClient(create_app(_config(tmp_path)))

    # Two writes → two revisions.
    client.put("/api/projects/alpha/memories/CLAUDE.md", json={"content": "v1"})
    client.put("/api/projects/alpha/memories/CLAUDE.md", json={"content": "v22"})

    r = client.get("/api/projects/alpha/memory-history?file=CLAUDE.md")
    assert r.status_code == 200
    body = r.json()
    assert body["project"] == "alpha"
    assert body["file"] == "CLAUDE.md"
    assert body["count"] == 2
    revs = body["revisions"]
    # Newest first.
    assert revs[0]["id"] > revs[1]["id"]
    assert "saved_at" in revs[0]
    # Content is NOT in the metadata response.
    assert "content" not in revs[0]


def test_get_memory_history_requires_file_query(tmp_path: Path) -> None:
    _make_project_dir(tmp_path, "alpha")
    client = TestClient(create_app(_config(tmp_path)))
    r = client.get("/api/projects/alpha/memory-history?file=")
    assert r.status_code == 400


def test_get_memory_revision_returns_content(tmp_path: Path) -> None:
    p = _make_project_dir(tmp_path, "alpha")
    (p / "CLAUDE.md").write_text("v0", encoding="utf-8")
    client = TestClient(create_app(_config(tmp_path)))

    client.put("/api/projects/alpha/memories/CLAUDE.md", json={"content": "PAYLOAD"})
    history = memory_revisions.history(project="alpha", file="CLAUDE.md")
    rev_id = history[0].id

    r = client.get(
        f"/api/projects/alpha/memory-revisions/{rev_id}?file=CLAUDE.md",
    )
    assert r.status_code == 200
    assert r.text == "PAYLOAD"
    assert r.headers["content-type"].startswith("text/markdown")


def test_get_memory_revision_404_unknown_id(tmp_path: Path) -> None:
    _make_project_dir(tmp_path, "alpha")
    client = TestClient(create_app(_config(tmp_path)))
    r = client.get(
        "/api/projects/alpha/memory-revisions/9999?file=CLAUDE.md",
    )
    assert r.status_code == 404


def test_get_memory_revision_400_invalid_project(tmp_path: Path) -> None:
    client = TestClient(create_app(_config(tmp_path)))
    r = client.get(
        "/api/projects/..%2Fbad/memory-revisions/1?file=CLAUDE.md",
    )
    # Either FastAPI's path-validation rejects, or our validator does.
    assert r.status_code in (400, 404)


def test_history_panel_link_present_in_template(tmp_path: Path) -> None:
    p = _make_project_dir(tmp_path, "alpha")
    (p / "CLAUDE.md").write_text("x", encoding="utf-8")
    client = TestClient(create_app(_config(tmp_path)))
    r = client.get("/projects/alpha")
    assert r.status_code == 200
    body = r.text
    # v19.0.0a6: the legacy memoriesPanel "Toggle revision history" button
    # was replaced by an inline "diff vs:" dropdown on the new
    # memoriesEditor toolbar; the equivalent revision-loader is
    # `loadRevisions` (not `loadHistory`). The /api/.../memory-history
    # endpoint contract is unchanged — still queried via ?file=.
    assert 'aria-label="Diff against revision"' in body
    assert "loadRevisions" in body
    assert "memory-history" in body

"""v13.0.0a3: side-by-side HTML diff renderer + reembed diff parity.

Two related diff endpoints ship together:

  - GET /api/projects/{name}/memory-revisions/diff?format=html
      Returns text/html — `difflib.HtmlDiff().make_table` side-by-side
      output (line numbers + change highlights) instead of the
      v12.0.0a4 unified-diff text.

  - GET /api/history/reembed/runs/diff?from=I&to=J
      Returns JSON delta of two reembed runs (per-field diff +
      duration). Mirrors the memory-revision diff pattern for the
      v7.0.0a4 reembed history.
"""
from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from harbormaster.config import HarbormasterConfig, ProjectsConfig
from harbormaster.ui import create_app
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


# -- format=html branch ------------------------------------------------


def test_html_diff_returns_html_table(tmp_path: Path) -> None:
    p = _make_project_dir(tmp_path, "alpha")
    (p / "CLAUDE.md").write_text("hello\n", encoding="utf-8")
    client = TestClient(create_app(_config(tmp_path)))

    client.put(
        "/api/projects/alpha/memories/CLAUDE.md",
        json={"content": "hello world\n"},
    )
    (p / "CLAUDE.md").write_text("hello\nfresh\n", encoding="utf-8")
    history = client.get(
        "/api/projects/alpha/memory-history?file=CLAUDE.md",
    ).json()
    rev_id = history["revisions"][-1]["id"]

    r = client.get(
        f"/api/projects/alpha/memory-revisions/diff?from={rev_id}"
        f"&file=CLAUDE.md&format=html",
    )
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")
    body = r.text
    # HtmlDiff emits a <table class="diff"> ... </table> fragment.
    assert "<table" in body and 'class="diff"' in body
    # Side-by-side has both column headers from fromdesc / todesc.
    assert f"revision {rev_id}" in body
    assert "current" in body


def test_html_diff_two_revisions(tmp_path: Path) -> None:
    p = _make_project_dir(tmp_path, "alpha")
    (p / "CLAUDE.md").write_text("ignored\n", encoding="utf-8")
    client = TestClient(create_app(_config(tmp_path)))

    client.put("/api/projects/alpha/memories/CLAUDE.md", json={"content": "v1\n"})
    client.put("/api/projects/alpha/memories/CLAUDE.md", json={"content": "v2\n"})
    revisions = client.get(
        "/api/projects/alpha/memory-history?file=CLAUDE.md",
    ).json()["revisions"]
    newer, older = revisions[0]["id"], revisions[1]["id"]

    r = client.get(
        f"/api/projects/alpha/memory-revisions/diff?from={older}&to={newer}"
        f"&file=CLAUDE.md&format=html",
    )
    assert r.status_code == 200
    body = r.text
    assert f"revision {older}" in body
    assert f"revision {newer}" in body
    # Change highlight class is one of HtmlDiff's standard markers.
    assert "diff_chg" in body or "diff_add" in body or "diff_sub" in body


def test_unified_format_default_preserved(tmp_path: Path) -> None:
    """v12.0.0a4 contract: default format is unified text. Catches
    accidental flip of the default in the v13.0.0a3 refactor."""
    p = _make_project_dir(tmp_path, "alpha")
    (p / "CLAUDE.md").write_text("hello\n", encoding="utf-8")
    client = TestClient(create_app(_config(tmp_path)))
    client.put(
        "/api/projects/alpha/memories/CLAUDE.md",
        json={"content": "hello world\n"},
    )
    rev_id = client.get(
        "/api/projects/alpha/memory-history?file=CLAUDE.md",
    ).json()["revisions"][-1]["id"]
    r = client.get(
        f"/api/projects/alpha/memory-revisions/diff?from={rev_id}&file=CLAUDE.md",
    )
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/plain")


def test_unknown_format_returns_400(tmp_path: Path) -> None:
    p = _make_project_dir(tmp_path, "alpha")
    (p / "CLAUDE.md").write_text("hello\n", encoding="utf-8")
    client = TestClient(create_app(_config(tmp_path)))
    client.put(
        "/api/projects/alpha/memories/CLAUDE.md",
        json={"content": "hello world\n"},
    )
    rev_id = client.get(
        "/api/projects/alpha/memory-history?file=CLAUDE.md",
    ).json()["revisions"][-1]["id"]
    r = client.get(
        f"/api/projects/alpha/memory-revisions/diff?from={rev_id}"
        f"&file=CLAUDE.md&format=junk",
    )
    assert r.status_code == 400


# -- reembed runs diff -------------------------------------------------


def _seed_reembed_history(history_path: Path) -> None:
    """Write two synthetic ReembedRunRecord rows to a temp history
    file so the diff endpoint has something to compare."""
    payload = [
        {
            "started_at": 1000.0,
            "finished_at": 1010.0,
            "total": 100,
            "succeeded": 95,
            "failed": 5,
            "cancelled": 0,
            "model": "BAAI/bge-small-en-v1.5",
        },
        {
            "started_at": 2000.0,
            "finished_at": 2025.0,
            "total": 110,
            "succeeded": 108,
            "failed": 2,
            "cancelled": 0,
            "model": "BAAI/bge-small-en-v1.5",
        },
    ]
    history_path.write_text(json.dumps(payload), encoding="utf-8")


def test_reembed_runs_diff_basic(
    tmp_path: Path, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    history = tmp_path / "reembed_history.json"
    _seed_reembed_history(history)
    monkeypatch.setenv("HARBORMASTER_REEMBED_HISTORY_FILE", str(history))

    client = TestClient(create_app(_config(tmp_path)))
    r = client.get("/api/history/reembed/runs/diff?from=0&to=1")
    assert r.status_code == 200
    body = r.json()
    assert body["from_index"] == 0
    assert body["to_index"] == 1
    assert body["delta"]["total"] == 10
    assert body["delta"]["succeeded"] == 13
    assert body["delta"]["failed"] == -3
    assert body["delta"]["cancelled"] == 0
    assert body["delta"]["duration_seconds"] == 15.0
    assert body["delta"]["model_changed"] is False


def test_reembed_runs_diff_model_changed(
    tmp_path: Path, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    history = tmp_path / "reembed_history.json"
    payload = [
        {
            "started_at": 1.0, "finished_at": 2.0,
            "total": 1, "succeeded": 1, "failed": 0, "cancelled": 0,
            "model": "old",
        },
        {
            "started_at": 3.0, "finished_at": 4.0,
            "total": 1, "succeeded": 1, "failed": 0, "cancelled": 0,
            "model": "new",
        },
    ]
    history.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setenv("HARBORMASTER_REEMBED_HISTORY_FILE", str(history))

    client = TestClient(create_app(_config(tmp_path)))
    r = client.get("/api/history/reembed/runs/diff?from=0&to=1")
    assert r.status_code == 200
    assert r.json()["delta"]["model_changed"] is True


def test_reembed_runs_diff_404_when_index_oob(
    tmp_path: Path, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    history = tmp_path / "reembed_history.json"
    _seed_reembed_history(history)
    monkeypatch.setenv("HARBORMASTER_REEMBED_HISTORY_FILE", str(history))
    client = TestClient(create_app(_config(tmp_path)))
    r = client.get("/api/history/reembed/runs/diff?from=0&to=99")
    assert r.status_code == 404
    r = client.get("/api/history/reembed/runs/diff?from=-1&to=0")
    assert r.status_code == 404


def test_reembed_runs_diff_returns_full_records(
    tmp_path: Path, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    """The endpoint must include both ReembedRunRecord dicts so the UI
    can render the side-by-side without a second fetch."""
    history = tmp_path / "reembed_history.json"
    _seed_reembed_history(history)
    monkeypatch.setenv("HARBORMASTER_REEMBED_HISTORY_FILE", str(history))
    client = TestClient(create_app(_config(tmp_path)))
    body = client.get(
        "/api/history/reembed/runs/diff?from=0&to=1",
    ).json()
    assert body["from"]["total"] == 100
    assert body["to"]["total"] == 110
    assert body["from"]["model"] == "BAAI/bge-small-en-v1.5"

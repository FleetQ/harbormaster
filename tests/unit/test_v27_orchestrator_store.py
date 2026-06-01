"""v27.0.0 — orchestrator column: migration + persistence round-trip."""
from __future__ import annotations

import sqlite3
from pathlib import Path

from harbormaster.jobs.schema import STATUS_AWAITING_CALLER
from harbormaster.jobs.store import JobStore


def _pre_v27_schema(path: Path) -> None:
    """A v26.1-shape table (has batch_id, lacks orchestrator)."""
    conn = sqlite3.connect(str(path))
    conn.execute(
        "CREATE TABLE delegated_jobs ("
        "id TEXT PRIMARY KEY,"
        " inbox_id TEXT NOT NULL DEFAULT 'default',"
        " project TEXT NOT NULL, host TEXT, task TEXT NOT NULL,"
        " deliverable TEXT NOT NULL, allow_writes INTEGER NOT NULL,"
        " model TEXT, status TEXT NOT NULL, output TEXT, error TEXT, cid TEXT,"
        " queued_at REAL NOT NULL, started_at REAL, completed_at REAL,"
        " duration_ms INTEGER, read_at REAL,"
        " max_turns INTEGER NOT NULL DEFAULT 10,"
        " auto_commit INTEGER NOT NULL DEFAULT 0,"
        " execution_mode TEXT NOT NULL DEFAULT 'subprocess',"
        " tokens_used INTEGER, rendered_prompt TEXT, batch_id TEXT"
        ")"
    )
    conn.execute(
        "INSERT INTO delegated_jobs ("
        "id, inbox_id, project, host, task, deliverable, allow_writes,"
        " model, status, queued_at, max_turns, auto_commit, execution_mode"
        ") VALUES ('d_legacy', 'default', 'old', NULL, 't', 'd', 1,"
        " NULL, 'completed', 1700000000.0, 10, 0, 'subprocess')"
    )
    conn.commit()
    conn.close()


def test_pre_v27_db_migrates_to_add_orchestrator_column(tmp_path: Path):
    db = tmp_path / "legacy.db"
    _pre_v27_schema(db)
    store = JobStore(db)
    cols = {
        row["name"]
        for row in store._conn.execute("PRAGMA table_info(delegated_jobs)")
    }
    assert "orchestrator" in cols
    job = store.get("d_legacy")
    assert job is not None
    assert job.orchestrator is None  # legacy rows have NULL
    store.close()


def test_enqueue_persists_orchestrator(tmp_path: Path):
    store = JobStore(tmp_path / "jobs.db")
    job = store.enqueue(
        project="p", host=None, task="t", deliverable="d",
        allow_writes=False, model=None,
        execution_mode="instruction",
        initial_status=STATUS_AWAITING_CALLER,
        orchestrator="codex",
    )
    got = store.get(job.id)
    assert got is not None
    assert got.orchestrator == "codex"
    assert got.as_dict()["orchestrator"] == "codex"
    store.close()


def test_enqueue_default_orchestrator_is_none(tmp_path: Path):
    store = JobStore(tmp_path / "jobs.db")
    job = store.enqueue(
        project="p", host=None, task="t", deliverable="d",
        allow_writes=False, model=None,
    )
    got = store.get(job.id)
    assert got is not None
    assert got.orchestrator is None
    store.close()

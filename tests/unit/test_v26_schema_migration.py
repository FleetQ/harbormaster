"""v26.0.0 — schema migration tests for execution_mode + tokens_used."""
from __future__ import annotations

import sqlite3
from pathlib import Path

from harbormaster.jobs.schema import STATUS_AWAITING_CALLER, VALID_STATUSES
from harbormaster.jobs.store import JobStore


def _pre_v26_schema(path: Path) -> None:
    """Recreate a v25-shape delegated_jobs table (no execution_mode,
    no tokens_used) so we can verify the idempotent migration."""
    conn = sqlite3.connect(str(path))
    conn.execute(
        "CREATE TABLE delegated_jobs ("
        "id TEXT PRIMARY KEY,"
        " inbox_id TEXT NOT NULL DEFAULT 'default',"
        " project TEXT NOT NULL,"
        " host TEXT,"
        " task TEXT NOT NULL,"
        " deliverable TEXT NOT NULL,"
        " allow_writes INTEGER NOT NULL,"
        " model TEXT,"
        " status TEXT NOT NULL,"
        " output TEXT, error TEXT, cid TEXT,"
        " queued_at REAL NOT NULL, started_at REAL,"
        " completed_at REAL, duration_ms INTEGER,"
        " read_at REAL,"
        " max_turns INTEGER NOT NULL DEFAULT 10,"
        " auto_commit INTEGER NOT NULL DEFAULT 0"
        ")"
    )
    conn.execute(
        "INSERT INTO delegated_jobs ("
        "id, inbox_id, project, host, task, deliverable,"
        " allow_writes, model, status, queued_at, max_turns, auto_commit"
        ") VALUES ('d_legacy', 'default', 'old', NULL, 't', 'd',"
        " 1, NULL, 'completed', 1700000000.0, 10, 0)"
    )
    conn.commit()
    conn.close()


def test_pre_v26_db_migrates_to_add_execution_mode_column(tmp_path: Path):
    db = tmp_path / "legacy.db"
    _pre_v26_schema(db)
    # Opening through JobStore triggers _apply_migrations.
    store = JobStore(db)
    # Verify the new columns exist.
    cols = {
        row["name"] for row in store._conn.execute(
            "PRAGMA table_info(delegated_jobs)",
        ).fetchall()
    }
    assert "execution_mode" in cols
    assert "tokens_used" in cols
    # Verify the legacy row got the subprocess default.
    job = store.get("d_legacy")
    assert job is not None
    assert job.execution_mode == "subprocess"
    assert job.tokens_used is None
    store.close()


def test_v26_db_open_is_idempotent(tmp_path: Path):
    """Opening a fresh v26-shape DB and re-opening it must not error."""
    db = tmp_path / "fresh.db"
    JobStore(db).close()
    # Re-open. Migration loop should be a no-op (every column already
    # present in PRAGMA table_info).
    store = JobStore(db)
    cols = {
        row["name"] for row in store._conn.execute(
            "PRAGMA table_info(delegated_jobs)",
        ).fetchall()
    }
    assert "execution_mode" in cols
    assert "tokens_used" in cols
    store.close()


def test_status_awaiting_caller_in_valid_statuses():
    assert STATUS_AWAITING_CALLER == "awaiting_caller"
    assert STATUS_AWAITING_CALLER in VALID_STATUSES

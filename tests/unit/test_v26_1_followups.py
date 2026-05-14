"""v26.0.1 followup tests — batch_id correlation, JobWorker CAS parity."""
from __future__ import annotations

from pathlib import Path

import pytest

from harbormaster.config import DelegateConfig, HarbormasterConfig, ProjectsConfig
from harbormaster.jobs.schema import (
    STATUS_AWAITING_CALLER,
    STATUS_COMPLETED,
    STATUS_RUNNING,
)
from harbormaster.jobs.store import JobStore
from harbormaster.server import build_server


def _tools(mcp):
    return {t.name: t for t in mcp._tool_manager.list_tools()}


@pytest.fixture
def jobs_db(tmp_path, monkeypatch):
    db = tmp_path / "jobs.db"
    monkeypatch.setenv("HARBORMASTER_JOBS_DB", str(db))
    from harbormaster.jobs import subsystem as _sub
    if _sub._singleton is not None:
        _sub.shutdown_subsystem()
    yield db
    if _sub._singleton is not None:
        _sub.shutdown_subsystem()


@pytest.fixture
def two_projects(tmp_path):
    a = tmp_path / "alpha"
    b = tmp_path / "beta"
    a.mkdir()
    b.mkdir()
    (a / "CLAUDE.md").write_text("# alpha\n")
    (b / "CLAUDE.md").write_text("# beta\n")
    return tmp_path, ["alpha", "beta"]


def _cfg(root: Path, **overrides):
    return HarbormasterConfig(
        projects=ProjectsConfig(glob=[str(root) + "/*"]),
        delegate=DelegateConfig(**overrides),
    )


# ─── batch_id correlation ────────────────────────────────────────────


def test_fan_out_persists_shared_batch_id_on_every_row(
    jobs_db, two_projects,
):
    root, names = two_projects
    cfg = _cfg(root)
    fn = _tools(build_server(cfg))["fan_out_ask"].fn
    fn(question="what?", project_filter=names)

    from harbormaster.jobs import get_subsystem
    rows = get_subsystem(cfg).store.list_recent(
        status=STATUS_AWAITING_CALLER, limit=10,
    )
    assert len(rows) == 2
    batch_ids = {r.batch_id for r in rows}
    assert len(batch_ids) == 1, f"expected one batch_id, got {batch_ids}"
    bid = batch_ids.pop()
    assert bid is not None
    assert bid.startswith("batch_")


def test_fan_out_packet_envelope_uses_same_batch_id(jobs_db, two_projects):
    root, names = two_projects
    cfg = _cfg(root)
    fn = _tools(build_server(cfg))["fan_out_ask"].fn
    packet = fn(question="what?", project_filter=names)

    from harbormaster.jobs import get_subsystem
    rows = get_subsystem(cfg).store.list_recent(
        status=STATUS_AWAITING_CALLER, limit=10,
    )
    assert rows
    bid = rows[0].batch_id
    assert bid is not None
    # The envelope's batch_id matches the per-row batch_id.
    assert bid in packet


def test_list_recent_filters_by_batch_id(jobs_db, two_projects):
    root, names = two_projects
    cfg = _cfg(root)
    fn = _tools(build_server(cfg))["fan_out_ask"].fn

    # Two distinct fan-out invocations → two distinct batch_ids.
    fn(question="q1", project_filter=names)
    fn(question="q2", project_filter=names)

    from harbormaster.jobs import get_subsystem
    store = get_subsystem(cfg).store
    all_rows = store.list_recent(limit=20)
    batches = {r.batch_id for r in all_rows if r.batch_id}
    assert len(batches) == 2

    for bid in batches:
        filtered = store.list_recent(batch_id=bid, limit=10)
        assert len(filtered) == 2
        assert all(r.batch_id == bid for r in filtered)


def test_single_target_delegate_has_null_batch_id(jobs_db, tmp_path):
    project = tmp_path / "p"
    project.mkdir()
    (project / "CLAUDE.md").write_text("# p\n")
    cfg = _cfg(tmp_path)
    fn = _tools(build_server(cfg))["delegate_task"].fn
    fn(name="p", task="t", deliverable="d")

    from harbormaster.jobs import get_subsystem
    rows = get_subsystem(cfg).store.list_recent(
        status=STATUS_AWAITING_CALLER, limit=5,
    )
    assert rows
    assert all(r.batch_id is None for r in rows)


def test_pre_v26_1_db_migrates_to_add_batch_id_column(tmp_path: Path):
    """A db without the batch_id column gets it via idempotent migration."""
    db = tmp_path / "legacy_v26.db"
    # Build a v26.0.0-shape table (no batch_id column).
    import sqlite3
    conn = sqlite3.connect(str(db))
    conn.executescript(
        "CREATE TABLE delegated_jobs ("
        " id TEXT PRIMARY KEY, inbox_id TEXT NOT NULL DEFAULT 'default',"
        " project TEXT NOT NULL, host TEXT, task TEXT NOT NULL,"
        " deliverable TEXT NOT NULL, allow_writes INTEGER NOT NULL,"
        " model TEXT, status TEXT NOT NULL, output TEXT, error TEXT,"
        " cid TEXT, queued_at REAL NOT NULL, started_at REAL,"
        " completed_at REAL, duration_ms INTEGER, read_at REAL,"
        " max_turns INTEGER NOT NULL DEFAULT 10,"
        " auto_commit INTEGER NOT NULL DEFAULT 0,"
        " execution_mode TEXT NOT NULL DEFAULT 'subprocess',"
        " tokens_used INTEGER, rendered_prompt TEXT"
        ");"
    )
    conn.commit()
    conn.close()

    store = JobStore(db)
    cols = {
        row["name"] for row in store._conn.execute(
            "PRAGMA table_info(delegated_jobs)",
        ).fetchall()
    }
    assert "batch_id" in cols
    store.close()


# ─── JobWorker CAS parity ────────────────────────────────────────────


def test_worker_complete_uses_expected_status(tmp_path: Path):
    """v26.0.1: JobWorker.complete must pass expected_status=STATUS_RUNNING
    so a second-writer race is rejected at the CAS guard."""
    store = JobStore(tmp_path / "jobs.db")
    job = store.enqueue(
        project="p", host=None, task="t", deliverable="d",
        allow_writes=False, model=None,
    )
    # Atomically advance to running.
    claimed = store.claim_next_queued()
    assert claimed is not None
    assert claimed.id == job.id

    # First write should succeed.
    first = store.complete(
        job.id, output="ok", duration_ms=10,
        expected_status=STATUS_RUNNING,
    )
    assert first is True

    # Second write with same guard — row is no longer running → False.
    second = store.complete(
        job.id, output="late", duration_ms=10,
        expected_status=STATUS_RUNNING,
    )
    assert second is False

    final = store.get(job.id)
    assert final is not None
    assert final.status == STATUS_COMPLETED
    assert final.output == "ok"
    store.close()


def test_worker_fail_uses_expected_status(tmp_path: Path):
    store = JobStore(tmp_path / "jobs.db")
    job = store.enqueue(
        project="p", host=None, task="t", deliverable="d",
        allow_writes=False, model=None,
    )
    store.claim_next_queued()

    first = store.fail(
        job.id, error="oh no", cid=None, duration_ms=10,
        expected_status=STATUS_RUNNING,
    )
    assert first is True

    second = store.fail(
        job.id, error="redo", cid=None, duration_ms=10,
        expected_status=STATUS_RUNNING,
    )
    assert second is False
    store.close()

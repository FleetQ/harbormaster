"""Unit tests for the async-delegate JobStore (v22.0.0a2)."""
from __future__ import annotations

from pathlib import Path

import pytest

from harbormaster.jobs.schema import (
    STATUS_COMPLETED,
    STATUS_FAILED,
    STATUS_QUEUED,
    STATUS_RUNNING,
)
from harbormaster.jobs.store import (
    MAX_RECOVERY_ATTEMPTS,
    JobStore,
    OrphanRecovery,
)


@pytest.fixture
def store(tmp_path: Path) -> JobStore:
    return JobStore(tmp_path / "jobs.db")


def test_enqueue_returns_queued_job(store: JobStore):
    job = store.enqueue(
        project="alpha",
        host=None,
        task="audit",
        deliverable="report",
        allow_writes=False,
        model=None,
    )
    assert job.id.startswith("d_")
    assert job.status == STATUS_QUEUED
    assert job.project == "alpha"
    assert job.queued_at > 0
    assert job.started_at is None
    assert job.completed_at is None


def test_get_returns_none_for_unknown_id(store: JobStore):
    assert store.get("d_doesnotexist") is None


def test_claim_next_queued_marks_running(store: JobStore):
    a = store.enqueue(
        project="alpha", host=None, task="t1", deliverable="d1",
        allow_writes=False, model=None,
    )
    b = store.enqueue(
        project="beta", host=None, task="t2", deliverable="d2",
        allow_writes=False, model=None,
    )

    first = store.claim_next_queued()
    assert first is not None
    assert first.id == a.id
    assert first.status == STATUS_RUNNING
    assert first.started_at is not None

    second = store.claim_next_queued()
    assert second is not None
    assert second.id == b.id


def test_claim_next_queued_returns_none_when_empty(store: JobStore):
    assert store.claim_next_queued() is None


def test_claim_next_queued_is_atomic_across_threads(store: JobStore):
    """Two concurrent claims must each get a unique job — the
    UPDATE ... RETURNING SQL must not race."""
    import concurrent.futures

    ids = []
    for _ in range(20):
        job = store.enqueue(
            project="alpha", host=None, task="t", deliverable="d",
            allow_writes=False, model=None,
        )
        ids.append(job.id)

    seen: list[str] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as pool:
        results = list(pool.map(lambda _: store.claim_next_queued(), range(20)))

    seen = [j.id for j in results if j is not None]
    assert sorted(seen) == sorted(ids)


def test_complete_marks_completed_with_output(store: JobStore):
    job = store.enqueue(
        project="alpha", host=None, task="t", deliverable="d",
        allow_writes=False, model=None,
    )
    store.claim_next_queued()
    store.complete(job.id, output="done!", duration_ms=42)
    final = store.get(job.id)
    assert final is not None
    assert final.status == STATUS_COMPLETED
    assert final.output == "done!"
    assert final.duration_ms == 42
    assert final.completed_at is not None


def test_fail_marks_failed_with_error_and_cid(store: JobStore):
    job = store.enqueue(
        project="alpha", host=None, task="t", deliverable="d",
        allow_writes=False, model=None,
    )
    store.claim_next_queued()
    store.fail(
        job.id, error="Error: ... [cid=abc12345] — code=timeout: ...",
        cid="abc12345", duration_ms=10,
    )
    final = store.get(job.id)
    assert final is not None
    assert final.status == STATUS_FAILED
    assert "code=timeout" in (final.error or "")
    assert final.cid == "abc12345"


def test_recover_orphaned_requeues_readonly_job(store: JobStore):
    # v28.0.0 — a read-only job left ``running`` by a crash is re-queued
    # (safe to re-run), not failed, and the worker can re-claim it.
    job = store.enqueue(
        project="alpha", host=None, task="t", deliverable="d",
        allow_writes=False, model=None,
    )
    store.claim_next_queued()  # → running

    recovered = store.recover_orphaned()
    assert recovered == OrphanRecovery(requeued=1, failed=0)

    requeued = store.get(job.id)
    assert requeued is not None
    assert requeued.status == STATUS_QUEUED
    assert requeued.error is None
    assert requeued.started_at is None

    reclaimed = store.claim_next_queued()
    assert reclaimed is not None
    assert reclaimed.id == job.id
    assert reclaimed.status == STATUS_RUNNING


def test_recover_orphaned_fails_write_jobs(store: JobStore):
    # A write job's dead subprocess may have applied partial edits, so it
    # is failed (a human decides), never silently re-run.
    job = store.enqueue(
        project="alpha", host=None, task="t", deliverable="d",
        allow_writes=True, model=None,
    )
    store.claim_next_queued()  # → running

    recovered = store.recover_orphaned()
    assert recovered == OrphanRecovery(requeued=0, failed=1)

    final = store.get(job.id)
    assert final is not None
    assert final.status == STATUS_FAILED
    assert "re-delegate manually" in (final.error or "")


def test_recover_orphaned_caps_requeue(store: JobStore):
    # A read-only job that keeps getting orphaned must not re-queue
    # forever — after MAX_RECOVERY_ATTEMPTS it is failed (poison-pill guard).
    assert MAX_RECOVERY_ATTEMPTS == 1
    job = store.enqueue(
        project="alpha", host=None, task="t", deliverable="d",
        allow_writes=False, model=None,
    )

    store.claim_next_queued()  # → running (attempt 1)
    first = store.recover_orphaned()
    assert first == OrphanRecovery(requeued=1, failed=0)
    assert store.get(job.id).status == STATUS_QUEUED  # type: ignore[union-attr]

    store.claim_next_queued()  # → running (attempt 2)
    second = store.recover_orphaned()
    assert second == OrphanRecovery(requeued=0, failed=1)
    final = store.get(job.id)
    assert final is not None
    assert final.status == STATUS_FAILED


def test_recover_orphaned_summary_counts_mixed_batch(store: JobStore):
    for allow in (False, False, True):
        store.enqueue(
            project="alpha", host=None, task="t", deliverable="d",
            allow_writes=allow, model=None,
        )
    for _ in range(3):
        store.claim_next_queued()  # all → running

    recovered = store.recover_orphaned()
    assert recovered.requeued == 2
    assert recovered.failed == 1
    assert recovered.total == 3


def test_list_recent_filters_by_project_and_status(store: JobStore):
    store.enqueue(
        project="alpha", host=None, task="t", deliverable="d",
        allow_writes=False, model=None,
    )
    store.enqueue(
        project="beta", host=None, task="t", deliverable="d",
        allow_writes=False, model=None,
    )
    j3 = store.enqueue(
        project="alpha", host=None, task="t", deliverable="d",
        allow_writes=False, model=None,
    )
    store.claim_next_queued()  # alpha first
    store.complete(j3.id, output="x", duration_ms=1)
    # actually first claim returned the oldest (alpha #1), not j3 —
    # complete on j3 still works because complete doesn't check status.

    alpha_jobs = store.list_recent(project="alpha")
    assert len(alpha_jobs) == 2
    assert all(j.project == "alpha" for j in alpha_jobs)

    queued_jobs = store.list_recent(status=STATUS_QUEUED)
    # j2 (beta) is still queued; alpha #1 is running; j3 is completed
    assert {j.project for j in queued_jobs} == {"beta"}


def test_enqueue_stores_max_turns(store: JobStore):
    """v22.0.1: per-job max_turns is persisted and round-trips."""
    default_job = store.enqueue(
        project="alpha", host=None, task="t", deliverable="d",
        allow_writes=False, model=None,
    )
    custom_job = store.enqueue(
        project="alpha", host=None, task="t", deliverable="d",
        allow_writes=False, model=None, max_turns=75,
    )
    assert default_job.max_turns == 10
    assert custom_job.max_turns == 75
    reloaded_default = store.get(default_job.id)
    reloaded_custom = store.get(custom_job.id)
    assert reloaded_default is not None and reloaded_default.max_turns == 10
    assert reloaded_custom is not None and reloaded_custom.max_turns == 75


def test_migration_adds_max_turns_to_pre_v22_0_1_db(tmp_path):
    """An existing v22.0.0 DB lacking max_turns gets the column
    on next open. Reproduces the upgrade-in-place path."""
    import sqlite3

    db = tmp_path / "legacy.db"
    # Hand-craft a v22.0.0 schema (no max_turns column).
    conn = sqlite3.connect(str(db))
    conn.executescript(
        """
        CREATE TABLE delegated_jobs (
            id TEXT PRIMARY KEY,
            inbox_id TEXT NOT NULL DEFAULT 'default',
            project TEXT NOT NULL,
            host TEXT, task TEXT NOT NULL, deliverable TEXT NOT NULL,
            allow_writes INTEGER NOT NULL, model TEXT,
            status TEXT NOT NULL, output TEXT, error TEXT, cid TEXT,
            queued_at REAL NOT NULL, started_at REAL, completed_at REAL,
            duration_ms INTEGER, read_at REAL
        );
        INSERT INTO delegated_jobs (
          id, project, task, deliverable, allow_writes, status, queued_at
        ) VALUES ('d_legacy01', 'alpha', 't', 'd', 0, 'completed', 1.0);
        """
    )
    conn.close()

    # Open through JobStore — _apply_migrations should ADD COLUMN.
    store = JobStore(db)
    job = store.get("d_legacy01")
    assert job is not None
    assert job.max_turns == 10  # default backfill


def test_inbox_pending_excludes_running_and_read(store: JobStore):
    j1 = store.enqueue(
        project="alpha", host=None, task="t", deliverable="d",
        allow_writes=False, model=None, inbox_id="sprint-1",
    )
    # j2 and j3 are setup-only — we want them to exist in different
    # states (running / queued-in-other-inbox) so the pending filter
    # has something to reject.
    store.enqueue(
        project="alpha", host=None, task="t", deliverable="d",
        allow_writes=False, model=None, inbox_id="sprint-1",
    )
    store.enqueue(
        project="alpha", host=None, task="t", deliverable="d",
        allow_writes=False, model=None, inbox_id="sprint-2",
    )

    store.claim_next_queued()  # j1 running
    store.complete(j1.id, output="ok", duration_ms=1)
    store.claim_next_queued()  # j2 running (still running)
    # j3 stays queued (different inbox)

    pending = store.list_pending_for_inbox("sprint-1")
    assert [j.id for j in pending] == [j1.id]

    # mark j1 read → pending becomes empty
    n = store.mark_read([j1.id])
    assert n == 1
    assert store.list_pending_for_inbox("sprint-1") == []

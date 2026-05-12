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
from harbormaster.jobs.store import JobStore


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


def test_recover_orphaned_promotes_running_to_failed(store: JobStore):
    j1 = store.enqueue(
        project="alpha", host=None, task="t", deliverable="d",
        allow_writes=False, model=None,
    )
    j2 = store.enqueue(
        project="alpha", host=None, task="t", deliverable="d",
        allow_writes=False, model=None,
    )
    store.claim_next_queued()  # j1 → running
    store.claim_next_queued()  # j2 → running

    recovered = store.recover_orphaned()
    assert recovered == 2
    for jid in (j1.id, j2.id):
        final = store.get(jid)
        assert final is not None
        assert final.status == STATUS_FAILED
        assert final.error == "server_restart"


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

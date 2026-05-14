"""v26.0.0 — record_delegation_result MCP tool tests."""
from __future__ import annotations

import threading
import time

import pytest

from harbormaster.config import DelegateConfig, HarbormasterConfig
from harbormaster.jobs.schema import (
    STATUS_AWAITING_CALLER,
    STATUS_COMPLETED,
    STATUS_FAILED,
    STATUS_QUEUED,
)
from harbormaster.server import build_server


def _tools(mcp):
    return {t.name: t for t in mcp._tool_manager.list_tools()}


@pytest.fixture
def jobs_db(tmp_path, monkeypatch):
    """Force the JobStore singleton onto a fresh per-test SQLite file
    and tear the singleton down afterwards."""
    db = tmp_path / "jobs.db"
    monkeypatch.setenv("HARBORMASTER_JOBS_DB", str(db))
    # Reset the singleton so each test gets a fresh subsystem.
    from harbormaster.jobs import subsystem as _sub
    if _sub._singleton is not None:
        _sub.shutdown_subsystem()
    yield db
    if _sub._singleton is not None:
        _sub.shutdown_subsystem()


def _enqueue_instruction(config, *, allow_writes=False):
    from harbormaster.jobs import get_subsystem
    sub = get_subsystem(config)
    return sub.store.enqueue(
        project="p", host=None, task="t", deliverable="d",
        allow_writes=allow_writes, model=None,
        inbox_id="default", max_turns=10, auto_commit=False,
        execution_mode="instruction",
        initial_status=STATUS_AWAITING_CALLER,
    )


def test_record_completed_transitions_status(jobs_db):
    cfg = HarbormasterConfig()
    job = _enqueue_instruction(cfg)
    mcp = build_server(cfg)
    fn = _tools(mcp)["record_delegation_result"].fn
    out = fn(
        job_id=job.id, status="completed", output="all done",
        duration_ms=1234, tokens_used=5678,
    )
    assert "recorded" in out
    from harbormaster.jobs import get_subsystem
    updated = get_subsystem(cfg).store.get(job.id)
    assert updated is not None
    assert updated.status == STATUS_COMPLETED
    assert updated.output == "all done"
    assert updated.duration_ms == 1234
    assert updated.tokens_used == 5678


def test_record_failed_transitions_status(jobs_db):
    cfg = HarbormasterConfig()
    job = _enqueue_instruction(cfg)
    mcp = build_server(cfg)
    fn = _tools(mcp)["record_delegation_result"].fn
    out = fn(
        job_id=job.id, status="failed",
        error="agent_timeout", duration_ms=300,
    )
    assert "failed" in out
    from harbormaster.jobs import get_subsystem
    updated = get_subsystem(cfg).store.get(job.id)
    assert updated is not None
    assert updated.status == STATUS_FAILED
    assert updated.error == "agent_timeout"


def test_record_unknown_job_returns_error(jobs_db):
    cfg = HarbormasterConfig()
    mcp = build_server(cfg)
    fn = _tools(mcp)["record_delegation_result"].fn
    out = fn(job_id="d_does_not_exist", status="completed", output="x")
    assert out.startswith("Error: job ")
    assert "not found" in out


def test_record_idempotent_same_status(jobs_db):
    cfg = HarbormasterConfig()
    job = _enqueue_instruction(cfg)
    mcp = build_server(cfg)
    fn = _tools(mcp)["record_delegation_result"].fn
    fn(job_id=job.id, status="completed", output="first")
    out = fn(job_id=job.id, status="completed", output="second")
    assert "idempotent" in out
    from harbormaster.jobs import get_subsystem
    updated = get_subsystem(cfg).store.get(job.id)
    assert updated is not None
    # Idempotent re-record must not clobber existing terminal payload.
    assert updated.output == "first"


def test_record_conflicting_terminal_status_rejected(jobs_db):
    cfg = HarbormasterConfig()
    job = _enqueue_instruction(cfg)
    mcp = build_server(cfg)
    fn = _tools(mcp)["record_delegation_result"].fn
    fn(job_id=job.id, status="completed", output="ok")
    out = fn(job_id=job.id, status="failed", error="late_failure")
    assert out.startswith("Error: job ")
    assert "already in terminal state" in out


def test_record_fires_event_for_wait_for_job(jobs_db):
    cfg = HarbormasterConfig()
    job = _enqueue_instruction(cfg)
    mcp = build_server(cfg)
    fn = _tools(mcp)["record_delegation_result"].fn
    from harbormaster.jobs import get_subsystem
    sub = get_subsystem(cfg)

    captured: dict[str, object] = {}

    def waiter():
        captured["job"] = sub.store.wait_for_job(job.id, timeout_seconds=2)

    t = threading.Thread(target=waiter)
    t.start()
    # Give the waiter a moment to register the Event.
    time.sleep(0.05)
    fn(job_id=job.id, status="completed", output="done", duration_ms=10)
    t.join(timeout=3)
    completed = captured.get("job")
    assert completed is not None
    assert completed.status == STATUS_COMPLETED  # type: ignore[union-attr]


def test_record_subprocess_mode_job_rejected(jobs_db):
    """A row enqueued via subprocess path must not be recorded by the
    caller — that's the JobWorker's job."""
    cfg = HarbormasterConfig()
    from harbormaster.jobs import get_subsystem
    sub = get_subsystem(cfg)
    # Default enqueue → subprocess + queued.
    job = sub.store.enqueue(
        project="p", host=None, task="t", deliverable="d",
        allow_writes=False, model=None,
    )
    assert job.execution_mode == "subprocess"
    assert job.status == STATUS_QUEUED

    mcp = build_server(cfg)
    fn = _tools(mcp)["record_delegation_result"].fn
    out = fn(job_id=job.id, status="completed", output="caller intrusion")
    assert out.startswith("Error: job ")
    assert "not 'instruction'" in out


def test_record_completed_missing_output_rejected(jobs_db):
    cfg = HarbormasterConfig()
    job = _enqueue_instruction(cfg)
    mcp = build_server(cfg)
    fn = _tools(mcp)["record_delegation_result"].fn
    out = fn(job_id=job.id, status="completed")
    assert "requires output" in out


def test_record_failed_missing_error_rejected(jobs_db):
    cfg = HarbormasterConfig()
    job = _enqueue_instruction(cfg)
    mcp = build_server(cfg)
    fn = _tools(mcp)["record_delegation_result"].fn
    out = fn(job_id=job.id, status="failed")
    assert "requires error" in out


def test_record_after_concurrent_completion_with_conflicting_status(jobs_db):
    """v26 fix: when a concurrent writer transitions the row to
    completed and the second caller tries to record it as failed,
    the second call must be rejected — not silently transition.
    Output from the first writer is preserved."""
    cfg = HarbormasterConfig()
    job = _enqueue_instruction(cfg)
    from harbormaster.jobs import get_subsystem
    sub = get_subsystem(cfg)
    # Pre-transition via the store directly (simulates a concurrent
    # writer winning the race).
    sub.store.complete(
        job.id, output="from_other_caller", duration_ms=5,
        expected_status=STATUS_AWAITING_CALLER,
    )

    mcp = build_server(cfg)
    fn = _tools(mcp)["record_delegation_result"].fn
    # Conflicting terminal: caller wants to record as failed, but
    # the row is already completed.
    out = fn(job_id=job.id, status="failed", error="late_failure")
    assert "already in terminal state" in out
    # Output of the first writer must be preserved.
    final = sub.store.get(job.id)
    assert final is not None
    assert final.output == "from_other_caller"
    assert final.status == STATUS_COMPLETED


def test_record_cas_rejects_when_status_transitions_between_read_and_update(
    jobs_db, monkeypatch,
):
    """Tighter TOCTOU test: monkeypatch store.get to make
    record_delegation_result believe the row is awaiting_caller,
    while in reality it has already transitioned. The CAS UPDATE
    inside complete() must find rowcount=0 and the tool must
    return the 'transitioned out of awaiting_caller during record'
    error rather than silently overwriting."""
    cfg = HarbormasterConfig()
    job = _enqueue_instruction(cfg)
    from harbormaster.jobs import get_subsystem
    sub = get_subsystem(cfg)
    # Directly transition the row out from under any prospective
    # record_delegation_result call.
    sub.store.complete(
        job.id, output="stolen_by_other_writer", duration_ms=5,
        expected_status=STATUS_AWAITING_CALLER,
    )

    # Inject a stale get() that still reports awaiting_caller so
    # record_delegation_result's status check passes — emulating the
    # window where two callers both passed the check.
    real_get = sub.store.get
    from harbormaster.jobs.store import Job

    def stale_get(jid):
        if jid != job.id:
            return real_get(jid)
        # Reuse the real row but force status back to awaiting_caller.
        actual = real_get(jid)
        if actual is None:
            return None
        return Job(
            id=actual.id, inbox_id=actual.inbox_id, project=actual.project,
            host=actual.host, task=actual.task, deliverable=actual.deliverable,
            allow_writes=actual.allow_writes, model=actual.model,
            status=STATUS_AWAITING_CALLER,
            output=None, error=None, cid=None,
            queued_at=actual.queued_at, started_at=None,
            completed_at=None, duration_ms=None, read_at=None,
            max_turns=actual.max_turns, auto_commit=actual.auto_commit,
            execution_mode=actual.execution_mode,
            tokens_used=actual.tokens_used,
            rendered_prompt=actual.rendered_prompt,
        )

    monkeypatch.setattr(sub.store, "get", stale_get)

    mcp = build_server(cfg)
    fn = _tools(mcp)["record_delegation_result"].fn
    out = fn(job_id=job.id, status="completed", output="late_arrival")
    assert "transitioned out of awaiting_caller" in out

    # Real state is unchanged — first writer's payload preserved.
    monkeypatch.undo()
    final = sub.store.get(job.id)
    assert final is not None
    assert final.status == STATUS_COMPLETED
    assert final.output == "stolen_by_other_writer"


def test_complete_with_expected_status_rejects_wrong_state(jobs_db):
    """Optimistic CAS on store.complete returns False when the row
    is not in the expected status."""
    cfg = HarbormasterConfig()
    job = _enqueue_instruction(cfg)
    from harbormaster.jobs import get_subsystem
    sub = get_subsystem(cfg)

    # First update transitions to completed.
    assert sub.store.complete(
        job.id, output="first", duration_ms=1,
        expected_status=STATUS_AWAITING_CALLER,
    ) is True
    # Second update with the same guard must return False — no
    # row matches the predicate any more.
    assert sub.store.complete(
        job.id, output="second", duration_ms=1,
        expected_status=STATUS_AWAITING_CALLER,
    ) is False


def test_sweep_with_exclude_ids_protects_self(jobs_db):
    """sweep_stale_awaiting_caller honours exclude_ids — the row
    being recorded must never be swept out from under the caller."""
    cfg = HarbormasterConfig(
        delegate=DelegateConfig(awaiting_caller_timeout_seconds=1),
    )
    from harbormaster.jobs import get_subsystem
    sub = get_subsystem(cfg)
    # Insert a stale row that WOULD be swept.
    sub.store._conn.execute(
        "INSERT INTO delegated_jobs ("
        "id, inbox_id, project, host, task, deliverable,"
        " allow_writes, model, status, queued_at, max_turns,"
        " auto_commit, execution_mode"
        ") VALUES ('d_keep', 'default', 'p', NULL, 't', 'd',"
        " 0, NULL, ?, ?, 10, 0, 'instruction')",
        (STATUS_AWAITING_CALLER, time.time() - 10),
    )
    sub.store._conn.execute(
        "INSERT INTO delegated_jobs ("
        "id, inbox_id, project, host, task, deliverable,"
        " allow_writes, model, status, queued_at, max_turns,"
        " auto_commit, execution_mode"
        ") VALUES ('d_sweep', 'default', 'p', NULL, 't', 'd',"
        " 0, NULL, ?, ?, 10, 0, 'instruction')",
        (STATUS_AWAITING_CALLER, time.time() - 10),
    )
    sub.store._conn.commit()

    swept = sub.store.sweep_stale_awaiting_caller(
        max_age_seconds=1, exclude_ids=frozenset({"d_keep"}),
    )
    assert swept == 1
    assert sub.store.get("d_keep").status == STATUS_AWAITING_CALLER
    assert sub.store.get("d_sweep").status == STATUS_FAILED


def test_record_triggers_sweep_of_stale_awaiting_caller(jobs_db, monkeypatch):
    """Calling record_delegation_result should opportunistically sweep
    any stale awaiting_caller rows older than the configured TTL."""
    cfg = HarbormasterConfig(
        delegate=DelegateConfig(awaiting_caller_timeout_seconds=1),
    )
    from harbormaster.jobs import get_subsystem
    sub = get_subsystem(cfg)

    # Stale row: queued_at well in the past.
    stale_id = "d_stale_xx"
    sub.store._conn.execute(
        "INSERT INTO delegated_jobs ("
        "id, inbox_id, project, host, task, deliverable,"
        " allow_writes, model, status, queued_at, max_turns,"
        " auto_commit, execution_mode"
        ") VALUES (?, 'default', 'p', NULL, 't', 'd',"
        " 0, NULL, ?, ?, 10, 0, 'instruction')",
        (stale_id, STATUS_AWAITING_CALLER, time.time() - 10),
    )
    sub.store._conn.commit()

    # Fresh row to actually record.
    fresh = _enqueue_instruction(cfg)

    mcp = build_server(cfg)
    fn = _tools(mcp)["record_delegation_result"].fn
    fn(job_id=fresh.id, status="completed", output="ok", duration_ms=1)

    # Stale should have been swept inside the record call.
    stale = sub.store.get(stale_id)
    assert stale is not None
    assert stale.status == STATUS_FAILED
    assert stale.error == "caller_never_recorded_result"

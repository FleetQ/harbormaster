"""Unit tests for the JobWorker (v22.0.0a2).

These exercise the worker in isolation by stubbing ``run_backend`` —
no subprocess is spawned. The fake_claude-driven end-to-end is covered
separately in ``tests/integration/test_jobs_e2e.py``.
"""
from __future__ import annotations

import time
from pathlib import Path

from harbormaster.config import HarbormasterConfig
from harbormaster.jobs.schema import STATUS_COMPLETED, STATUS_FAILED
from harbormaster.jobs.store import JobStore
from harbormaster.jobs.worker import JobWorker, _extract_cid


def _wait_until(predicate, timeout: float = 2.0, poll: float = 0.02):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate():
            return True
        time.sleep(poll)
    return False


def test_extract_cid_pulls_id_from_run_backend_error_shape():
    msg = (
        "Error: delegate(name='alpha', host='local') failed after 1234 ms "
        "[cid=abcdef01] — code=timeout: claude -p exceeded 60s"
    )
    assert _extract_cid(msg) == "abcdef01"


def test_extract_cid_returns_none_when_no_marker():
    assert _extract_cid("Error: bare validation failure") is None


def test_worker_completes_queued_job(tmp_path: Path, monkeypatch):
    """Happy path: enqueue → worker claims → run_backend returns
    normal text → row goes to status='completed' with the output."""
    from harbormaster.jobs import worker as _worker

    monkeypatch.setattr(
        _worker,
        "run_backend",
        lambda **_: "FAKE_RESULT body text",
    )
    monkeypatch.setattr(
        _worker,
        "build_grounded_prompt",
        lambda **kwargs: f"GROUND[{kwargs['project']}]: {kwargs['question']}",
    )

    store = JobStore(tmp_path / "jobs.db")
    job = store.enqueue(
        project="alpha", host=None, task="t", deliverable="d",
        allow_writes=False, model=None,
    )

    w = JobWorker(config=HarbormasterConfig(), store=store, poll_interval_s=0.01)
    w.start()
    try:
        assert _wait_until(lambda: (g := store.get(job.id)) is not None and g.status == STATUS_COMPLETED)
    finally:
        w.stop(timeout=1.0)

    final = store.get(job.id)
    assert final is not None
    assert final.status == STATUS_COMPLETED
    assert final.output == "FAKE_RESULT body text"
    assert final.duration_ms is not None and final.duration_ms >= 0


def test_worker_records_failure_when_run_backend_returns_error_string(
    tmp_path: Path, monkeypatch,
):
    """run_backend returns ``Error: ...`` instead of raising on
    BackendError — worker must detect the prefix and mark failed."""
    from harbormaster.jobs import worker as _worker

    monkeypatch.setattr(
        _worker,
        "run_backend",
        lambda **_: (
            "Error: delegate.async(name='alpha', host='local') "
            "failed after 5 ms [cid=deadbeef] — code=timeout: ..."
        ),
    )
    monkeypatch.setattr(
        _worker,
        "build_grounded_prompt",
        lambda **kwargs: "x",
    )

    store = JobStore(tmp_path / "jobs.db")
    job = store.enqueue(
        project="alpha", host=None, task="t", deliverable="d",
        allow_writes=False, model=None,
    )

    w = JobWorker(config=HarbormasterConfig(), store=store, poll_interval_s=0.01)
    w.start()
    try:
        assert _wait_until(lambda: (g := store.get(job.id)) is not None and g.status == STATUS_FAILED)
    finally:
        w.stop(timeout=1.0)

    final = store.get(job.id)
    assert final is not None
    assert final.status == STATUS_FAILED
    assert "code=timeout" in (final.error or "")
    assert final.cid == "deadbeef"


def test_worker_processes_multiple_jobs_in_order(tmp_path: Path, monkeypatch):
    from harbormaster.jobs import worker as _worker

    monkeypatch.setattr(
        _worker, "run_backend", lambda **kw: f"RESULT for {kw['name']}",
    )
    monkeypatch.setattr(_worker, "build_grounded_prompt", lambda **k: "x")

    store = JobStore(tmp_path / "jobs.db")
    ids = [
        store.enqueue(
            project=f"proj-{i}", host=None, task="t", deliverable="d",
            allow_writes=False, model=None,
        ).id
        for i in range(5)
    ]

    w = JobWorker(config=HarbormasterConfig(), store=store, poll_interval_s=0.01)
    w.start()
    try:
        assert _wait_until(
            lambda: all(
                (g := store.get(jid)) is not None
                and g.status == STATUS_COMPLETED
                for jid in ids
            ),
            timeout=3.0,
        )
    finally:
        w.stop(timeout=1.0)

    for i, jid in enumerate(ids):
        final = store.get(jid)
        assert final is not None
        assert final.output == f"RESULT for proj-{i}"


def test_worker_stop_is_idempotent(tmp_path: Path, monkeypatch):
    from harbormaster.jobs import worker as _worker

    monkeypatch.setattr(_worker, "run_backend", lambda **_: "ok")
    monkeypatch.setattr(_worker, "build_grounded_prompt", lambda **k: "x")

    store = JobStore(tmp_path / "jobs.db")
    w = JobWorker(config=HarbormasterConfig(), store=store, poll_interval_s=0.01)
    w.start()
    w.stop(timeout=1.0)
    # Second stop must not raise.
    w.stop(timeout=0.1)


def test_subsystem_lazy_init_and_shutdown(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("HARBORMASTER_JOBS_DB", str(tmp_path / "subsystem.db"))
    from harbormaster.jobs import worker as _worker
    monkeypatch.setattr(_worker, "run_backend", lambda **_: "ok")
    monkeypatch.setattr(_worker, "build_grounded_prompt", lambda **k: "x")

    from harbormaster.jobs.subsystem import get_subsystem, shutdown_subsystem

    config = HarbormasterConfig()
    sub1 = get_subsystem(config)
    sub2 = get_subsystem(config)
    try:
        assert sub1 is sub2  # idempotent
        # store is usable
        job = sub1.store.enqueue(
            project="alpha", host=None, task="t", deliverable="d",
            allow_writes=False, model=None,
        )
        assert _wait_until(
            lambda: (g := sub1.store.get(job.id)) is not None
            and g.status == STATUS_COMPLETED,
        )
    finally:
        shutdown_subsystem()

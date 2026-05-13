"""Unit tests for v24.0.0a1 multi-worker JobWorker concurrency.

Validates that N workers against the same JobStore process all
queued jobs without double-claiming, and that subsystem boot wires
the configured worker_count.
"""
from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

from harbormaster.config import DelegateConfig, HarbormasterConfig
from harbormaster.jobs.schema import STATUS_COMPLETED
from harbormaster.jobs.subsystem import get_subsystem, shutdown_subsystem


@pytest.fixture(autouse=True)
def _isolate_subsystem():
    yield
    shutdown_subsystem()


def _wait_until(predicate, timeout: float = 5.0, poll: float = 0.02) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate():
            return True
        time.sleep(poll)
    return False


def test_subsystem_spawns_configured_worker_count(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("HARBORMASTER_JOBS_DB", str(tmp_path / "jobs.db"))
    config = HarbormasterConfig(delegate=DelegateConfig(worker_count=4))
    sub = get_subsystem(config)
    assert len(sub.workers) == 4
    assert all(w._thread is not None and w._thread.is_alive() for w in sub.workers)  # type: ignore[union-attr]
    # Backward-compat property still works.
    assert sub.worker is sub.workers[0]


def test_subsystem_default_is_single_worker(tmp_path: Path, monkeypatch):
    """v22/v23 backward-compat: bare HarbormasterConfig → 1 worker."""
    monkeypatch.setenv("HARBORMASTER_JOBS_DB", str(tmp_path / "jobs.db"))
    sub = get_subsystem(HarbormasterConfig())
    assert len(sub.workers) == 1


def test_multi_worker_processes_all_jobs_without_double_claim(
    tmp_path: Path, monkeypatch,
):
    """Atomic UPDATE ... RETURNING ensures each job is claimed by
    exactly one worker even under concurrent pressure."""
    from harbormaster.jobs import worker as _worker

    # Stub run_backend so we exercise threading, not subprocess.
    claim_log: list[str] = []
    log_lock = threading.Lock()

    def fake_run(*, name, **_kw):
        # Brief work + log claim.
        time.sleep(0.01)
        with log_lock:
            claim_log.append(name)
        return f"ok-{name}"

    monkeypatch.setattr(_worker, "run_backend", fake_run)
    monkeypatch.setattr(_worker, "build_grounded_prompt", lambda **k: "x")
    monkeypatch.setenv("HARBORMASTER_JOBS_DB", str(tmp_path / "jobs.db"))

    config = HarbormasterConfig(delegate=DelegateConfig(worker_count=4))
    sub = get_subsystem(config)

    # Enqueue 25 jobs. With 4 workers + atomic claim, each job lands
    # in exactly one worker's claim_log.
    ids: list[str] = []
    for i in range(25):
        j = sub.store.enqueue(
            project=f"proj-{i}", host=None, task="t", deliverable="d",
            allow_writes=False, model=None,
        )
        ids.append(j.id)

    assert _wait_until(
        lambda: all(
            (g := sub.store.get(jid)) is not None and g.status == STATUS_COMPLETED
            for jid in ids
        ),
        timeout=8.0,
    )

    # Every job processed exactly once.
    assert len(claim_log) == 25
    assert sorted(claim_log) == sorted(f"proj-{i}" for i in range(25))


def test_multi_worker_shutdown_stops_all_workers(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("HARBORMASTER_JOBS_DB", str(tmp_path / "jobs.db"))
    config = HarbormasterConfig(delegate=DelegateConfig(worker_count=3))
    sub = get_subsystem(config)
    threads = [w._thread for w in sub.workers]  # type: ignore[union-attr]
    assert all(t is not None and t.is_alive() for t in threads)

    shutdown_subsystem()
    # Each worker's thread should have joined.
    for t in threads:
        assert t is not None
        t.join(timeout=2.0)
        assert not t.is_alive()

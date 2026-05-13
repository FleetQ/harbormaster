"""Unit tests for ``JobStore.prune_old`` (v23.0.0a2).

Validates the retention pass that runs on subsystem boot:

- Most-recent ``retain`` rows always survive
- Older rows are deleted
- Currently queued / running rows are protected because their
  ``queued_at`` is recent
- ``retain < 1`` is a no-op (defensive)
"""
from __future__ import annotations

import time
from pathlib import Path

import pytest

from harbormaster.jobs.store import JobStore


@pytest.fixture
def store(tmp_path: Path) -> JobStore:
    return JobStore(tmp_path / "jobs.db")


def _seed_aged_row(store: JobStore, *, age_seconds: float) -> str:
    """Insert a completed row with queued_at backdated by ``age_seconds``."""
    job = store.enqueue(
        project="alpha", host=None, task="t", deliverable="d",
        allow_writes=False, model=None,
    )
    store.claim_next_queued()
    store.complete(job.id, output="x", duration_ms=1)
    # Backdate so it sorts as "old" for the prune query.
    with store._lock:
        store._conn.execute(
            "UPDATE delegated_jobs SET queued_at = ? WHERE id = ?",
            (time.time() - age_seconds, job.id),
        )
    return job.id


def test_prune_old_keeps_newest_retain_rows(store: JobStore):
    # Seed 10 rows, ages 100s, 90s, 80s ... 10s.
    ids = [
        _seed_aged_row(store, age_seconds=float(100 - i * 10))
        for i in range(10)
    ]
    # Keep the 3 newest. Older 7 should be deleted.
    deleted = store.prune_old(retain=3)
    assert deleted == 7

    survivors = store.list_recent(limit=20)
    # The 3 newest (age 10, 20, 30) survive in queued_at DESC order.
    assert {j.id for j in survivors} == set(ids[-3:])


def test_prune_old_with_retain_at_or_above_count_is_noop(store: JobStore):
    for _ in range(5):
        _seed_aged_row(store, age_seconds=1.0)
    # retain >= row count → nothing to delete.
    assert store.prune_old(retain=5) == 0
    assert store.prune_old(retain=100) == 0
    assert len(store.list_recent(limit=20)) == 5


def test_prune_old_with_retain_lt_1_is_noop(store: JobStore):
    """Defensive: retain=0 or negative is a no-op, not 'delete all'."""
    _seed_aged_row(store, age_seconds=1.0)
    assert store.prune_old(retain=0) == 0
    assert store.prune_old(retain=-1) == 0
    assert len(store.list_recent(limit=5)) == 1


def test_prune_old_protects_queued_jobs(store: JobStore):
    """A row sitting in ``queued`` has a recent ``queued_at`` and
    should always be in the 'newest N' bucket. Confirm we don't
    accidentally prune work-in-flight."""
    # Old completed row.
    _seed_aged_row(store, age_seconds=1000.0)
    # Fresh queued row.
    queued = store.enqueue(
        project="alpha", host=None, task="t", deliverable="d",
        allow_writes=False, model=None,
    )
    # retain=1 — should keep the queued one, prune the old completed.
    deleted = store.prune_old(retain=1)
    assert deleted == 1
    survivors = [j.id for j in store.list_recent(limit=5)]
    assert survivors == [queued.id]


def test_subsystem_boot_runs_prune_with_config_retain(
    tmp_path: Path, monkeypatch,
):
    """Subsystem init invokes prune_old with config.delegate.retain_recent_k."""
    monkeypatch.setenv("HARBORMASTER_JOBS_DB", str(tmp_path / "jobs.db"))

    # Pre-populate with 5 old rows on a STANDALONE store (before
    # subsystem boots). Then boot subsystem with retain=2 and verify
    # 3 got pruned at boot.
    pre = JobStore(tmp_path / "jobs.db")
    for _ in range(5):
        _seed_aged_row(pre, age_seconds=100.0)
    pre.close()

    from harbormaster.config import DelegateConfig, HarbormasterConfig
    from harbormaster.jobs.subsystem import (
        get_subsystem,
        shutdown_subsystem,
    )
    config = HarbormasterConfig(delegate=DelegateConfig(retain_recent_k=2))
    sub = get_subsystem(config)
    try:
        survivors = sub.store.list_recent(limit=20)
        assert len(survivors) == 2
    finally:
        shutdown_subsystem()

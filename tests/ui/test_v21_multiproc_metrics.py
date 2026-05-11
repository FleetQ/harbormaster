"""Cross-process dispatcher metrics aggregator (v21.0.0a8).

Validates ``harbormaster.dispatcher_metrics_store.DispatcherMetricsStore``:

  * round-trip: increments + decrements + snapshot reflect every write
  * concurrent writes from multiple threads (simulating multiple
    processes — SQLite WAL handles both cases the same way) don't lose
    updates
  * underflow is clamped at 0
  * DispatcherStats.snapshot() reflects writes made via a SEPARATE
    store instance pointed at the same DB (the multi-process case)
"""
from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

import pytest

from harbormaster.dispatcher_metrics_store import DispatcherMetricsStore


@pytest.fixture
def store(tmp_path: Path) -> DispatcherMetricsStore:
    return DispatcherMetricsStore(db_path=tmp_path / "metrics.db")


def test_roundtrip_increment_decrement_snapshot(store: DispatcherMetricsStore) -> None:
    store.increment_in_flight("ask_project")
    store.increment_in_flight("ask_project")
    store.increment_in_flight("list_projects")
    snap = store.snapshot()
    assert snap["tools"]["ask_project"]["in_flight"] == 2
    assert snap["tools"]["list_projects"]["in_flight"] == 1
    assert snap["active_workers"] == 3

    store.decrement_in_flight("ask_project", success=True)
    store.decrement_in_flight("list_projects", success=False)
    snap = store.snapshot()
    assert snap["tools"]["ask_project"]["in_flight"] == 1
    assert snap["tools"]["ask_project"]["total_completed"] == 1
    assert snap["tools"]["list_projects"]["in_flight"] == 0
    assert snap["tools"]["list_projects"]["total_failed"] == 1
    assert snap["active_workers"] == 1
    assert snap["last_dispatched_at"] is not None


def test_decrement_below_zero_is_clamped(store: DispatcherMetricsStore) -> None:
    # No prior increment — decrement should clamp at 0, not underflow.
    store.decrement_in_flight("ghost_tool", success=True)
    store.decrement_in_flight("ghost_tool", success=True)
    snap = store.snapshot()
    assert snap["tools"]["ghost_tool"]["in_flight"] == 0
    assert snap["tools"]["ghost_tool"]["total_completed"] == 2


def test_concurrent_writers_no_lost_updates(tmp_path: Path) -> None:
    """Simulate 4 concurrent writers (each represents a process)
    bumping in-flight 25 times each — the final counter must be 100."""
    db_path = tmp_path / "concurrent.db"
    # Pre-init schema in the parent so threads don't race the CREATE TABLE.
    DispatcherMetricsStore(db_path=db_path)
    barrier = threading.Barrier(4)

    def worker() -> None:
        store = DispatcherMetricsStore(db_path=db_path)
        barrier.wait()
        for _ in range(25):
            store.increment_in_flight("racey")

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    reader = DispatcherMetricsStore(db_path=db_path)
    snap = reader.snapshot()
    assert snap["tools"]["racey"]["in_flight"] == 100


def test_separate_store_instances_see_each_others_writes(tmp_path: Path) -> None:
    """Two store instances pointed at the same DB — the multi-process
    case in miniature."""
    db_path = tmp_path / "shared.db"
    store_a = DispatcherMetricsStore(db_path=db_path)
    store_b = DispatcherMetricsStore(db_path=db_path)

    store_a.increment_in_flight("ask_project")
    store_b.increment_in_flight("ask_project")
    store_a.decrement_in_flight("ask_project", success=True)

    snap_from_a = store_a.snapshot()
    snap_from_b = store_b.snapshot()
    assert snap_from_a == snap_from_b
    assert snap_from_a["tools"]["ask_project"]["in_flight"] == 1
    assert snap_from_a["tools"]["ask_project"]["total_completed"] == 1


def test_db_file_uses_wal_mode(tmp_path: Path) -> None:
    """WAL is what lets concurrent readers and writers coexist. Assert
    we actually enabled it so a future regression doesn't silently
    drop us back to rollback-journal mode."""
    db_path = tmp_path / "wal_check.db"
    DispatcherMetricsStore(db_path=db_path).increment_in_flight("seed")
    with sqlite3.connect(db_path) as conn:
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    assert mode.lower() == "wal"


def test_dispatcher_stats_snapshot_reflects_cross_process_writes(tmp_path: Path) -> None:
    """End-to-end: a SEPARATE DispatcherMetricsStore writes to the
    shared DB; DispatcherStats.snapshot() (wired to the same DB) sees
    the write. This is the path that lets harbormaster-mcp surface its
    own activity in the UI's /api/dispatcher/status payload."""
    from harbormaster.fleetq.dispatcher import DispatcherStats

    db_path = tmp_path / "e2e.db"
    shared_store = DispatcherMetricsStore(db_path=db_path)
    # Simulate the harbormaster-mcp process writing a dispatch.
    shared_store.increment_in_flight("ask_project")
    shared_store.decrement_in_flight("ask_project", success=True)

    # UI process: DispatcherStats wired to the same DB.
    ui_stats = DispatcherStats(store=DispatcherMetricsStore(db_path=db_path))
    snap = ui_stats.snapshot()
    assert snap["tools"]["ask_project"]["total_completed"] == 1
    assert snap["tools"]["ask_project"]["in_flight"] == 0
    # The running list is in-process — UI never started this span itself,
    # so the list is empty even though a peer process recorded the dispatch.
    assert snap["running"] == []


def test_reset_clears_all_counters(store: DispatcherMetricsStore) -> None:
    store.increment_in_flight("a")
    store.decrement_in_flight("a", success=True)
    store.reset()
    snap = store.snapshot()
    assert snap["tools"] == {}
    assert snap["active_workers"] == 0
    assert snap["last_dispatched_at"] is None

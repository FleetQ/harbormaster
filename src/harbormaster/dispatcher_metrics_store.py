"""Cross-process metrics store for the dispatcher (v21.0.0a8).

Long-deferred from v9.0.0a2: ``DispatcherStats`` is in-process, so the
``harbormaster-mcp`` (stdio/HTTP) and ``harbormaster-ui`` processes
each kept their own counters. The ``/api/dispatcher/status`` endpoint
served the UI process's view only.

This module provides a SQLite-backed counter store at
``~/.harbormaster/dispatcher_metrics.db`` so every process contributes
to one shared snapshot. The store ONLY tracks aggregate counters
(in-flight, total_completed, total_failed, last_dispatched_at). The
in-process ``DispatcherStats`` still owns the running-spans list and
the SSE subscriber set — those are inherently single-process.

Concurrency: WAL mode + transactional UPDATE statements give us
atomic increments without an external lock. SQLite handles
multi-writer contention by retrying on busy.
"""
from __future__ import annotations

import os
import sqlite3
import time
from pathlib import Path
from typing import Any

_DEFAULT_DB_NAME = "dispatcher_metrics.db"


def default_db_path() -> Path:
    """Return the canonical store path.

    Honours the ``HARBORMASTER_DISPATCHER_METRICS_DB`` env var (matching
    the ``HARBORMASTER_NETWORK_LOG_DB`` / ``HARBORMASTER_MEMORY_REVISIONS_DB``
    convention from v11). Tests redirect this in ``tests/conftest.py``.
    """
    override = os.environ.get("HARBORMASTER_DISPATCHER_METRICS_DB", "").strip()
    if override:
        return Path(override).expanduser()
    return Path.home() / ".harbormaster" / _DEFAULT_DB_NAME


class DispatcherMetricsStore:
    """Cross-process atomic counters for the dispatcher.

    All public methods open a short-lived connection per call. SQLite's
    own locking handles concurrent writers; WAL mode keeps readers
    non-blocking.
    """

    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = db_path or default_db_path()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        # Restrict directory perms — best-effort, no-op on non-POSIX.
        try:
            os.chmod(self.db_path.parent, 0o700)
        except OSError:
            pass
        self._init_schema()
        # File perms 0600 — best-effort.
        try:
            os.chmod(self.db_path, 0o600)
        except OSError:
            pass

    def _connect(self) -> sqlite3.Connection:
        # 5s busy timeout absorbs short contention windows during
        # concurrent multi-process writes.
        conn = sqlite3.connect(self.db_path, timeout=5.0, isolation_level=None)
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS counters (
                    tool TEXT PRIMARY KEY,
                    in_flight INTEGER NOT NULL DEFAULT 0,
                    total_completed INTEGER NOT NULL DEFAULT 0,
                    total_failed INTEGER NOT NULL DEFAULT 0,
                    last_dispatched_at REAL
                )
                """
            )

    def increment_in_flight(self, tool: str) -> None:
        """Atomically increment the in-flight counter for ``tool``."""
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO counters (tool, in_flight) VALUES (?, 1)
                ON CONFLICT(tool) DO UPDATE SET in_flight = in_flight + 1
                """,
                (tool,),
            )

    def decrement_in_flight(self, tool: str, success: bool) -> None:
        """Atomically decrement in-flight and bump the appropriate total.

        Clamps in-flight at 0 — a stray decrement (e.g. after a reset)
        won't underflow.
        """
        col = "total_completed" if success else "total_failed"
        now = time.time()
        with self._connect() as conn:
            conn.execute(
                f"""
                INSERT INTO counters (tool, in_flight, {col}, last_dispatched_at)
                VALUES (?, 0, 1, ?)
                ON CONFLICT(tool) DO UPDATE SET
                    in_flight = MAX(0, in_flight - 1),
                    {col} = {col} + 1,
                    last_dispatched_at = ?
                """,
                (tool, now, now),
            )

    def snapshot(self) -> dict[str, Any]:
        """Return the cross-process counter snapshot.

        Shape mirrors the legacy ``DispatcherStats.snapshot()`` payload
        minus the in-process-only fields (``running`` list). Callers
        that need the running-spans list (UI trace surface) merge it
        from the in-process ``DispatcherStats``.
        """
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT tool, in_flight, total_completed, total_failed, "
                "last_dispatched_at FROM counters"
            ).fetchall()
        tools: dict[str, dict[str, int]] = {}
        last_dispatched: float | None = None
        for tool, in_flight, total_completed, total_failed, last_at in rows:
            tools[tool] = {
                "in_flight": int(in_flight),
                "total_completed": int(total_completed),
                "total_failed": int(total_failed),
            }
            if last_at is not None and (last_dispatched is None or last_at > last_dispatched):
                last_dispatched = float(last_at)
        total_in_flight = sum(t["in_flight"] for t in tools.values())
        return {
            "active_workers": total_in_flight,
            "queue_depth": 0,
            "last_dispatched_at": last_dispatched,
            "tools": tools,
        }

    def reset(self) -> None:
        """Wipe every counter. Test helper — production code never calls this."""
        with self._connect() as conn:
            conn.execute("DELETE FROM counters")


# Process-wide singleton — created lazily so importing this module
# doesn't create the DB file (tests that point at a temp dir must
# install their own store before the first get_metrics_store() call).
_STORE: DispatcherMetricsStore | None = None


def get_metrics_store() -> DispatcherMetricsStore:
    global _STORE
    if _STORE is None:
        _STORE = DispatcherMetricsStore()
    return _STORE


def set_metrics_store(store: DispatcherMetricsStore | None) -> None:
    """Install a custom store (or clear it). Test-only."""
    global _STORE
    _STORE = store

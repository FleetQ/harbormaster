"""Thread-safe SQLite store for async delegated jobs (v22.0.0a2)."""
from __future__ import annotations

import secrets
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from harbormaster.jobs.schema import (
    MIGRATIONS,
    SCHEMA,
    STATUS_COMPLETED,
    STATUS_FAILED,
    STATUS_QUEUED,
    STATUS_RUNNING,
)


@dataclass(frozen=True)
class Job:
    """Typed view over one ``delegated_jobs`` row."""

    id: str
    inbox_id: str
    project: str
    host: str | None
    task: str
    deliverable: str
    allow_writes: bool
    model: str | None
    status: str
    output: str | None
    error: str | None
    cid: str | None
    queued_at: float
    started_at: float | None
    completed_at: float | None
    duration_ms: int | None
    read_at: float | None
    max_turns: int = 10

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable view (booleans normalised, no nulls
        for keys callers always expect)."""
        return {
            "job_id": self.id,
            "inbox_id": self.inbox_id,
            "project": self.project,
            "host": self.host,
            "task": self.task,
            "deliverable": self.deliverable,
            "allow_writes": self.allow_writes,
            "model": self.model,
            "status": self.status,
            "output": self.output,
            "error": self.error,
            "cid": self.cid,
            "queued_at": self.queued_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "duration_ms": self.duration_ms,
            "read_at": self.read_at,
            "max_turns": self.max_turns,
        }


def _row_to_job(row: sqlite3.Row) -> Job:
    return Job(
        id=row["id"],
        inbox_id=row["inbox_id"],
        project=row["project"],
        host=row["host"],
        task=row["task"],
        deliverable=row["deliverable"],
        allow_writes=bool(row["allow_writes"]),
        model=row["model"],
        status=row["status"],
        output=row["output"],
        error=row["error"],
        cid=row["cid"],
        queued_at=row["queued_at"],
        started_at=row["started_at"],
        completed_at=row["completed_at"],
        duration_ms=row["duration_ms"],
        read_at=row["read_at"],
        max_turns=row["max_turns"],
    )


class JobStore:
    """SQLite-backed store for async delegate jobs.

    Single connection guarded by ``threading.Lock`` — sqlite3 with WAL
    is fine for the modest write rate expected here (one
    enqueue + one complete per delegated call). The worker thread,
    enqueue calls from MCP tool handlers, and ``recall_pending_results``
    reads all share the lock to keep the contract simple.

    Use :func:`harbormaster.jobs.get_subsystem` rather than instantiating
    directly so callers share one store + one worker per process.
    """

    def __init__(self, db_path: Path):
        self._path = db_path
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(
            str(db_path), check_same_thread=False, isolation_level=None,
        )
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode = WAL")
        self._conn.execute("PRAGMA synchronous = NORMAL")
        self._conn.executescript(SCHEMA)
        self._lock = threading.Lock()
        self._apply_migrations()

    def _apply_migrations(self) -> None:
        """v22.0.1: idempotently ``ALTER TABLE ADD COLUMN`` for any
        entry in ``MIGRATIONS`` not already present. Pattern carried
        over from v21.0.8's ``network_log.db`` — PRAGMA table_info
        names every existing column, ALTER TABLE ADD only the missing
        ones.

        Schema-only migrations (column adds with simple defaults) are
        the only shape supported here. Anything that needs a data
        backfill belongs in an explicit one-shot helper.
        """
        with self._lock:
            existing = {
                row["name"] for row in self._conn.execute(
                    "PRAGMA table_info(delegated_jobs)",
                ).fetchall()
            }
            for name, ddl in MIGRATIONS:
                if name not in existing:
                    self._conn.execute(
                        f"ALTER TABLE delegated_jobs ADD COLUMN {ddl}",
                    )

    @staticmethod
    def _new_job_id() -> str:
        return "d_" + secrets.token_hex(6)

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def enqueue(
        self,
        *,
        project: str,
        host: str | None,
        task: str,
        deliverable: str,
        allow_writes: bool,
        model: str | None,
        inbox_id: str = "default",
        max_turns: int = 10,
    ) -> Job:
        """Insert a ``queued`` row and return its typed view.

        ``max_turns`` (v22.0.1) is the per-job turn budget the worker
        passes to ``run_backend``. Default 10 matches the pre-v22.0.1
        hardcoded value, so existing callers see identical behaviour.

        The worker thread polls for queued rows and claims them
        atomically via :meth:`claim_next_queued`.
        """
        job_id = self._new_job_id()
        now = time.time()
        with self._lock:
            self._conn.execute(
                "INSERT INTO delegated_jobs ("
                "id, inbox_id, project, host, task, deliverable, "
                "allow_writes, model, status, queued_at, max_turns"
                ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    job_id, inbox_id, project, host, task, deliverable,
                    1 if allow_writes else 0, model, STATUS_QUEUED, now,
                    max_turns,
                ),
            )
        job = self.get(job_id)
        if job is None:  # pragma: no cover — we just inserted it
            raise RuntimeError(f"enqueued job {job_id} disappeared")
        return job

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM delegated_jobs WHERE id = ?", (job_id,),
            ).fetchone()
        return _row_to_job(row) if row else None

    def claim_next_queued(self) -> Job | None:
        """Atomically pick the oldest ``queued`` row and mark it
        ``running``. Returns ``None`` if nothing is queued.

        The UPDATE ... RETURNING form is used so the read-then-write
        races nobody — between SELECT and UPDATE there is no window.
        """
        now = time.time()
        with self._lock:
            row = self._conn.execute(
                "UPDATE delegated_jobs SET status = ?, started_at = ? "
                "WHERE id = ("
                "  SELECT id FROM delegated_jobs WHERE status = ? "
                "  ORDER BY queued_at ASC LIMIT 1"
                ") "
                "RETURNING *",
                (STATUS_RUNNING, now, STATUS_QUEUED),
            ).fetchone()
        return _row_to_job(row) if row else None

    def complete(
        self, job_id: str, *, output: str, duration_ms: int,
    ) -> None:
        now = time.time()
        with self._lock:
            self._conn.execute(
                "UPDATE delegated_jobs "
                "SET status = ?, output = ?, completed_at = ?, duration_ms = ? "
                "WHERE id = ?",
                (STATUS_COMPLETED, output, now, duration_ms, job_id),
            )

    def fail(
        self,
        job_id: str,
        *,
        error: str,
        cid: str | None,
        duration_ms: int,
    ) -> None:
        now = time.time()
        with self._lock:
            self._conn.execute(
                "UPDATE delegated_jobs "
                "SET status = ?, error = ?, cid = ?, "
                "    completed_at = ?, duration_ms = ? "
                "WHERE id = ?",
                (STATUS_FAILED, error, cid, now, duration_ms, job_id),
            )

    def list_recent(
        self,
        *,
        project: str | None = None,
        status: str | None = None,
        limit: int = 50,
    ) -> list[Job]:
        clauses: list[str] = []
        params: list[Any] = []
        if project:
            clauses.append("project = ?")
            params.append(project)
        if status:
            clauses.append("status = ?")
            params.append(status)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(limit)
        with self._lock:
            rows = self._conn.execute(
                f"SELECT * FROM delegated_jobs {where} "
                "ORDER BY queued_at DESC LIMIT ?",
                params,
            ).fetchall()
        return [_row_to_job(r) for r in rows]

    def list_pending_for_inbox(
        self, inbox_id: str, *, limit: int = 50,
    ) -> list[Job]:
        """Completed or failed jobs in this inbox that have not yet
        been ``mark_read``."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM delegated_jobs "
                "WHERE inbox_id = ? "
                "  AND status IN (?, ?) "
                "  AND read_at IS NULL "
                "ORDER BY completed_at ASC LIMIT ?",
                (inbox_id, STATUS_COMPLETED, STATUS_FAILED, limit),
            ).fetchall()
        return [_row_to_job(r) for r in rows]

    def mark_read(self, job_ids: list[str]) -> int:
        if not job_ids:
            return 0
        now = time.time()
        placeholders = ",".join("?" for _ in job_ids)
        with self._lock:
            cur = self._conn.execute(
                f"UPDATE delegated_jobs SET read_at = ? "
                f"WHERE id IN ({placeholders}) AND read_at IS NULL",
                [now, *job_ids],
            )
            return cur.rowcount

    def recover_orphaned(self) -> int:
        """Mark any ``running`` rows as ``failed`` with reason
        ``server_restart``. Called once per process at subsystem init.

        Returns the count of rows recovered.
        """
        now = time.time()
        with self._lock:
            cur = self._conn.execute(
                "UPDATE delegated_jobs "
                "SET status = ?, error = ?, completed_at = ?, "
                "    duration_ms = COALESCE(duration_ms, 0) "
                "WHERE status = ?",
                (STATUS_FAILED, "server_restart", now, STATUS_RUNNING),
            )
            return cur.rowcount

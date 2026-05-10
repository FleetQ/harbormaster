"""v11.0.0a2: Memory revision history.

Every PUT/POST to a memory file appends a revision row to
`~/.harbormaster/memory_revisions.db`. The store keeps the last 20
revisions per (project, file) tuple — older entries are pruned on
each insert.

Schema (single table, migration-free for v11):

    CREATE TABLE memory_revisions (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      project TEXT NOT NULL,
      file TEXT NOT NULL,
      saved_at INTEGER NOT NULL,
      content TEXT NOT NULL,
      bytes_diff INTEGER
    );
    CREATE INDEX idx_memory_revisions_project_file
      ON memory_revisions(project, file, id DESC);

The DB file is created with mode 0600 — same convention as
`network_log.db`. Errors during writes are swallowed: revision
history is best-effort observability and must NEVER block the actual
memory write.
"""
from __future__ import annotations

import contextlib
import logging
import os
import sqlite3
import threading
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


# Per-(project, file) cap. 20 revisions is enough to recover from a
# week of daily edits while keeping the DB small.
MAX_REVISIONS_PER_FILE: int = 20

DEFAULT_DB_PATH = Path.home() / ".harbormaster" / "memory_revisions.db"


@dataclass(frozen=True)
class MemoryRevision:
    """One persisted revision."""

    id: int
    project: str
    file: str
    saved_at: int
    bytes_diff: int | None
    content: str | None = None  # populated only on full reads


def _resolve_db_path() -> Path:
    override = os.environ.get("HARBORMASTER_MEMORY_REVISIONS_DB", "").strip()
    return Path(override) if override else DEFAULT_DB_PATH


def _connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS memory_revisions (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          project TEXT NOT NULL,
          file TEXT NOT NULL,
          saved_at INTEGER NOT NULL,
          content TEXT NOT NULL,
          bytes_diff INTEGER
        );
        CREATE INDEX IF NOT EXISTS idx_memory_revisions_project_file
          ON memory_revisions(project, file, id DESC);
        """
    )
    conn.commit()
    try:
        os.chmod(db_path, 0o600)
    except OSError as e:
        logger.warning(
            "_connect: chmod 0600 failed for %s (%s) — continuing", db_path, e,
        )
    return conn


class MemoryRevisionsStore:
    """SQLite-backed per-file revision history.

    Public surface:
      - record(project, file, content, saved_at) → int (revision id)
      - history(project, file) → list[MemoryRevision]   (no content)
      - get_revision(project, file, rev_id) → MemoryRevision | None
      - clear() → None  (used by tests)
    """

    def __init__(
        self,
        db_path: Path | None = None,
        max_per_file: int = MAX_REVISIONS_PER_FILE,
    ) -> None:
        self._db_path = db_path or _resolve_db_path()
        self._max_per_file = max_per_file
        self._lock = threading.Lock()
        self._conn = _connect(self._db_path)

    def record(
        self,
        *,
        project: str,
        file: str,
        content: str,
        saved_at: int,
    ) -> int:
        """Persist a revision. Computes `bytes_diff` against the most
        recent revision for the same (project, file). Prunes older
        revisions beyond `max_per_file` after insert."""
        with self._lock:
            prior = self._conn.execute(
                "SELECT length(content) FROM memory_revisions "
                "WHERE project = ? AND file = ? "
                "ORDER BY id DESC LIMIT 1",
                (project, file),
            ).fetchone()
            prior_len = int(prior[0]) if prior else 0
            new_len = len(content.encode("utf-8"))
            bytes_diff = new_len - prior_len if prior else None

            cursor = self._conn.execute(
                "INSERT INTO memory_revisions "
                "(project, file, saved_at, content, bytes_diff) "
                "VALUES (?, ?, ?, ?, ?)",
                (project, file, saved_at, content, bytes_diff),
            )
            row_id = cursor.lastrowid or 0
            self._conn.commit()
            self._prune_locked(project, file)
        return int(row_id)

    def _prune_locked(self, project: str, file: str) -> None:
        self._conn.execute(
            "DELETE FROM memory_revisions "
            "WHERE project = ? AND file = ? AND id NOT IN ("
            " SELECT id FROM memory_revisions "
            " WHERE project = ? AND file = ? "
            " ORDER BY id DESC LIMIT ?"
            ")",
            (project, file, project, file, self._max_per_file),
        )
        self._conn.commit()

    def set_max_per_file(self, max_per_file: int) -> None:
        """v12.0.0a3: operator-configurable per-file cap.

        Updates `_max_per_file` and prunes every distinct
        (project, file) tuple under the new cap so a tightened limit
        takes effect immediately. Loosening is safe — `_prune_locked`
        is a no-op when row count is below the cap.
        """
        if max_per_file <= 0:
            raise ValueError("max_per_file must be > 0")
        with self._lock:
            self._max_per_file = max_per_file
            cursor = self._conn.execute(
                "SELECT DISTINCT project, file FROM memory_revisions",
            )
            tuples = cursor.fetchall()
        # _prune_locked acquires the lock itself per call; iterate
        # outside the lock so SQLite isn't held over many DELETEs.
        for project, file in tuples:
            with self._lock:
                self._prune_locked(str(project), str(file))

    def history(self, project: str, file: str) -> list[MemoryRevision]:
        """Return revisions descending by id (newest first), WITHOUT
        the `content` payload — that's a separate fetch via
        `get_revision()`."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, saved_at, bytes_diff FROM memory_revisions "
                "WHERE project = ? AND file = ? "
                "ORDER BY id DESC",
                (project, file),
            ).fetchall()
        return [
            MemoryRevision(
                id=int(r[0]),
                project=project,
                file=file,
                saved_at=int(r[1]),
                bytes_diff=int(r[2]) if r[2] is not None else None,
            )
            for r in rows
        ]

    def get_revision(
        self, project: str, file: str, rev_id: int,
    ) -> MemoryRevision | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT saved_at, bytes_diff, content FROM memory_revisions "
                "WHERE project = ? AND file = ? AND id = ?",
                (project, file, rev_id),
            ).fetchone()
        if not row:
            return None
        return MemoryRevision(
            id=rev_id,
            project=project,
            file=file,
            saved_at=int(row[0]),
            bytes_diff=int(row[1]) if row[1] is not None else None,
            content=str(row[2]),
        )

    def clear(self) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM memory_revisions")
            self._conn.commit()

    def close(self) -> None:
        with contextlib.suppress(Exception):
            self._conn.close()


# Module-level singleton, mirrors the pattern used by `network_log`.
memory_revisions = MemoryRevisionsStore()


__all__ = [
    "MAX_REVISIONS_PER_FILE",
    "MemoryRevision",
    "MemoryRevisionsStore",
    "memory_revisions",
]

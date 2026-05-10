"""v11.0.0a1: SQLite-backed persistent network log.

Replaces v10.0.0a7's in-process ring buffer (`_MCPCallLog`). Events
survive process restarts and can be aggregated across many runs. The
SSE fan-out for live subscribers is preserved so the UI still gets
push updates without polling.

Schema (single table, migration-free for v11):

    CREATE TABLE mcp_calls (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      timestamp INTEGER NOT NULL,
      source TEXT NOT NULL,        -- caller: "operator" or <project>
      target TEXT NOT NULL,
      tool TEXT NOT NULL,
      status TEXT NOT NULL,
      duration_ms INTEGER,
      question_preview TEXT
    );
    CREATE INDEX idx_mcp_calls_timestamp ON mcp_calls(timestamp DESC);

Rolling cap: 5000 rows. Pruning happens opportunistically after each
insert (every 100th insert performs a single DELETE that keeps the
last 5000 by id) so writes stay cheap on the hot path.

State file is `~/.harbormaster/network_log.db`, mode 0600 — same
convention as `bridge-state.json` and `reembed_history.json`.
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import sqlite3
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

logger = logging.getLogger(__name__)


NetworkTool = Literal[
    "ask_project",
    "delegate_task",
    "fan_out_ask",
    "recall_qa",
]

NetworkStatus = Literal["start", "ok", "error"]

# Rolling cap. ~5000 * ~400B per row = ~2MB on disk. Picked to cover
# several days of activity without bloating the file.
DEFAULT_MAX_ROWS: int = 5000

# Prune every Nth insert to amortise the DELETE cost. The cap can
# briefly overshoot by up to PRUNE_EVERY rows; harmless.
PRUNE_EVERY: int = 100

DEFAULT_DB_PATH = Path.home() / ".harbormaster" / "network_log.db"


@dataclass(frozen=True)
class NetworkEvent:
    """One MCP-tool dispatch recorded for the network view.

    Field shape preserved from v10.0.0a7 so existing UI consumers
    (graph + chat view) work without changes.
    """

    timestamp_ms: int
    caller: str
    target: str
    tool: str
    status: str
    question_preview: str
    duration_ms: int | None = None

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def _resolve_db_path() -> Path:
    override = os.environ.get("HARBORMASTER_NETWORK_LOG_DB", "").strip()
    return Path(override) if override else DEFAULT_DB_PATH


def _connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS mcp_calls (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          timestamp INTEGER NOT NULL,
          source TEXT NOT NULL,
          target TEXT NOT NULL,
          tool TEXT NOT NULL,
          status TEXT NOT NULL,
          duration_ms INTEGER,
          question_preview TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_mcp_calls_timestamp
          ON mcp_calls(timestamp DESC);
        """
    )
    conn.commit()
    # Tighten file permissions to match other ~/.harbormaster state files.
    try:
        os.chmod(db_path, 0o600)
    except OSError as e:
        logger.warning(
            "_connect: chmod 0600 failed for %s (%s) — continuing", db_path, e,
        )
    return conn


class NetworkStore:
    """SQLite-backed network event store with live SSE fan-out.

    Public surface mirrors v10's `_MCPCallLog`:
      - record(...) → NetworkEvent
      - recent(limit=None) → list[NetworkEvent]
      - subscribe() → asyncio.Queue
      - unsubscribe(q) → None
      - clear() → None  (used by tests)
    """

    def __init__(
        self,
        db_path: Path | None = None,
        max_rows: int = DEFAULT_MAX_ROWS,
    ) -> None:
        self._db_path = db_path or _resolve_db_path()
        self._max_rows = max_rows
        self._lock = threading.Lock()
        self._conn = _connect(self._db_path)
        self._insert_count = 0
        self._subscribers: list[asyncio.Queue[NetworkEvent]] = []

    def record(
        self,
        *,
        caller: str,
        target: str,
        tool: str,
        status: str = "ok",
        question_preview: str = "",
        duration_ms: int | None = None,
    ) -> NetworkEvent:
        ts_ms = int(time.time() * 1000)
        ev = NetworkEvent(
            timestamp_ms=ts_ms,
            caller=caller or "operator",
            target=target,
            tool=tool,
            status=status,
            question_preview=question_preview[:200],
            duration_ms=duration_ms,
        )
        with self._lock:
            self._conn.execute(
                "INSERT INTO mcp_calls "
                "(timestamp, source, target, tool, status, duration_ms, "
                " question_preview) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    ev.timestamp_ms,
                    ev.caller,
                    ev.target,
                    ev.tool,
                    ev.status,
                    ev.duration_ms,
                    ev.question_preview,
                ),
            )
            self._conn.commit()
            self._insert_count += 1
            if self._insert_count % PRUNE_EVERY == 0:
                self._prune_locked()
        self._notify(ev)
        return ev

    def _prune_locked(self) -> None:
        # Keep the last `max_rows` rows by id. SQLite handles the
        # subquery efficiently with the autoincrement primary key.
        self._conn.execute(
            "DELETE FROM mcp_calls WHERE id NOT IN ("
            " SELECT id FROM mcp_calls ORDER BY id DESC LIMIT ?"
            ")",
            (self._max_rows,),
        )
        self._conn.commit()

    def set_max_rows(self, max_rows: int) -> None:
        """v12.0.0a3: operator-configurable cap.

        Updates `_max_rows` and immediately prunes so a tightened cap
        takes effect on the very next `recent()` call instead of
        waiting for the next PRUNE_EVERY-th insert. Loosening the cap
        is also safe — no rows are touched on the prune call when the
        existing row count is below the new ceiling.
        """
        if max_rows <= 0:
            raise ValueError("max_rows must be > 0")
        with self._lock:
            self._max_rows = max_rows
            self._prune_locked()

    def recent(
        self,
        limit: int | None = None,
        *,
        tool: str | None = None,
        source: str | None = None,
        from_ms: int | None = None,
        to_ms: int | None = None,
    ) -> list[NetworkEvent]:
        """Return events in chronological (ASC) order, mirroring v10's
        deque-based ring buffer behaviour. When `limit` is set, returns
        the most recent N entries (still ASC).

        v13.0.0a4: optional filters apply server-side before LIMIT so
        the operator gets the most recent N matching events, not the
        most recent N events filtered to maybe-zero. All filters AND
        together; passing none preserves v10/v11/v12 behavior exactly.
        """
        actual_limit = limit if limit is not None else self._max_rows
        clauses: list[str] = []
        params: list[object] = []
        if tool is not None:
            clauses.append("tool = ?")
            params.append(tool)
        if source is not None:
            clauses.append("source = ?")
            params.append(source)
        if from_ms is not None:
            clauses.append("timestamp >= ?")
            params.append(from_ms)
        if to_ms is not None:
            clauses.append("timestamp <= ?")
            params.append(to_ms)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(actual_limit)
        with self._lock:
            cursor = self._conn.execute(
                "SELECT timestamp, source, target, tool, status, "
                " duration_ms, question_preview "
                f"FROM mcp_calls {where} "
                "ORDER BY id DESC "
                "LIMIT ?",
                params,
            )
            rows = cursor.fetchall()
        # Reverse to chronological ASC for parity with v10 deque order.
        rows.reverse()
        return [
            NetworkEvent(
                timestamp_ms=int(r[0]),
                caller=str(r[1]),
                target=str(r[2]),
                tool=str(r[3]),
                status=str(r[4]),
                duration_ms=int(r[5]) if r[5] is not None else None,
                question_preview=str(r[6] or ""),
            )
            for r in rows
        ]

    def subscribe(self) -> asyncio.Queue[NetworkEvent]:
        q: asyncio.Queue[NetworkEvent] = asyncio.Queue(maxsize=128)
        self._subscribers.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue[NetworkEvent]) -> None:
        with contextlib.suppress(ValueError):
            self._subscribers.remove(q)

    def _notify(self, ev: NetworkEvent) -> None:
        for q in self._subscribers:
            with contextlib.suppress(asyncio.QueueFull):
                q.put_nowait(ev)

    def stats(
        self, *, since_ms: int | None = None,
    ) -> dict[str, object]:
        """v11.0.0a6: aggregate metrics over rows newer than `since_ms`
        (epoch ms). Returns total_calls, by_tool dict, top_projects
        list, error_rate. When `since_ms` is None all rows are
        included.
        """
        params: list[object] = []
        where = ""
        if since_ms is not None:
            where = "WHERE timestamp >= ?"
            params.append(since_ms)
        with self._lock:
            total_row = self._conn.execute(
                f"SELECT COUNT(*) FROM mcp_calls {where}",
                params,
            ).fetchone()
            total = int(total_row[0]) if total_row else 0
            by_tool = {
                str(r[0]): int(r[1])
                for r in self._conn.execute(
                    f"SELECT tool, COUNT(*) FROM mcp_calls {where} "
                    "GROUP BY tool",
                    params,
                ).fetchall()
            }
            top_projects_rows = self._conn.execute(
                f"SELECT target, COUNT(*) AS c FROM mcp_calls {where} "
                "GROUP BY target ORDER BY c DESC LIMIT 5",
                params,
            ).fetchall()
            error_row = self._conn.execute(
                f"SELECT COUNT(*) FROM mcp_calls "
                f"{where} {'AND' if where else 'WHERE'} status = 'error'",
                params,
            ).fetchone()
            error_count = int(error_row[0]) if error_row else 0
            # v12.0.0a5: per-source (caller) breakdown — call counts +
            # error rate per origin. Lets the dashboard distinguish
            # operator-initiated calls from project-to-project routing.
            source_rows = self._conn.execute(
                f"SELECT source, COUNT(*) AS c, "
                f"  SUM(CASE WHEN status = 'error' THEN 1 ELSE 0 END) AS errs "
                f"FROM mcp_calls {where} GROUP BY source",
                params,
            ).fetchall()
            by_source = {
                str(r[0]): {
                    "calls": int(r[1]),
                    "error_rate": (
                        (int(r[2]) / int(r[1])) if int(r[1]) else 0.0
                    ),
                }
                for r in source_rows
            }
        return {
            "total_calls": total,
            "by_tool": by_tool,
            "by_source": by_source,
            "top_projects_by_calls": [
                {"project": str(r[0]), "count": int(r[1])}
                for r in top_projects_rows
            ],
            "error_rate": (error_count / total) if total else 0.0,
        }

    def clear(self) -> None:
        """Truncate the table. Used by tests to isolate state."""
        with self._lock:
            self._conn.execute("DELETE FROM mcp_calls")
            self._conn.commit()
            self._insert_count = 0

    def close(self) -> None:
        with contextlib.suppress(Exception):
            self._conn.close()

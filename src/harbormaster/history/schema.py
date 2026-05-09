"""Per-host sqlite schema for the Q&A history store.

One file per host (default `~/.harbormaster/qa_<sanitized_host>.db`).
Two tracks share the same `qa_log` table; only the auxiliary index
table differs:

  * vec  track: `qa_vec` virtual table backed by sqlite-vec (vec0).
  * fts  track: `qa_fts` virtual table backed by SQLite FTS5.

Both tracks are created lazily and idempotently. A single db file
may carry both — the store decides which to consult based on the
configured embedding_backend.
"""
from __future__ import annotations

import contextlib
import logging
import re
import sqlite3
from pathlib import Path

logger = logging.getLogger("harbormaster.history.schema")

# Embedding dimension for the default fastembed model
# (BAAI/bge-small-en-v1.5). Configurable via [history].embedding_dim
# but the schema commits to a single dim per db file — switching dim
# requires a fresh db file (we don't migrate vectors across dims).
HISTORY_VEC_DIM = 384

_HOST_SAFE = re.compile(r"[^A-Za-z0-9._-]")


def _sanitize_host(host: str | None) -> str:
    """Map a host label (or None for local) to a safe filename fragment."""
    if not host:
        return "local"
    safe = _HOST_SAFE.sub("_", host)
    return safe or "local"


def db_path_for_host(db_dir: str | Path, host: str | None) -> Path:
    """Resolve the db file path for a given host under db_dir."""
    base = Path(db_dir).expanduser()
    return base / f"qa_{_sanitize_host(host)}.db"


def _try_load_vec_extension(conn: sqlite3.Connection) -> bool:
    """Best-effort load of the sqlite-vec extension. Returns True on
    success, False otherwise. Failures are silent (debug log) — the
    caller may then fall back to the FTS5 path.
    """
    try:
        import sqlite_vec
    except ImportError:
        logger.debug("sqlite-vec not installed; vec track unavailable")
        return False

    try:
        conn.enable_load_extension(True)
    except (AttributeError, sqlite3.NotSupportedError) as e:
        logger.debug("sqlite-vec: cannot enable_load_extension: %s", e)
        return False

    try:
        sqlite_vec.load(conn)
    except sqlite3.OperationalError as e:
        logger.debug("sqlite-vec: load failed: %s", e)
        return False
    finally:
        with contextlib.suppress(sqlite3.NotSupportedError):
            conn.enable_load_extension(False)

    return True


def connect(db_path: str | Path) -> tuple[sqlite3.Connection, bool]:
    """Open a sqlite connection for the given path, creating parent
    directories if needed. Tries to load sqlite-vec; returns
    (conn, vec_loaded) so callers know whether the vec0 path is
    available without inspecting connection internals.
    """
    p = Path(db_path).expanduser()
    p.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(p)
    conn.row_factory = sqlite3.Row

    # PRAGMAs that pay for themselves on a long-lived single-writer db.
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA synchronous = NORMAL;")
    conn.execute("PRAGMA foreign_keys = ON;")

    vec_loaded = _try_load_vec_extension(conn)
    return conn, vec_loaded


_SCHEMA_BASE = """
CREATE TABLE IF NOT EXISTS qa_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    question TEXT NOT NULL,
    answer TEXT NOT NULL,
    project TEXT NOT NULL,
    host TEXT NOT NULL,
    tool TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    duration_ms INTEGER,
    cost_cents INTEGER,
    recall_count INTEGER NOT NULL DEFAULT 0,
    last_recalled_at INTEGER
);
CREATE INDEX IF NOT EXISTS idx_qa_log_created_at ON qa_log(created_at);
CREATE INDEX IF NOT EXISTS idx_qa_log_project ON qa_log(project);
CREATE INDEX IF NOT EXISTS idx_qa_log_recall_count ON qa_log(recall_count DESC);
"""

_SCHEMA_FTS = """
CREATE VIRTUAL TABLE IF NOT EXISTS qa_fts USING fts5(
    question,
    answer,
    content='qa_log',
    content_rowid='id',
    tokenize='porter unicode61'
);
"""

_FTS_TRIGGERS = """
CREATE TRIGGER IF NOT EXISTS qa_fts_ai AFTER INSERT ON qa_log BEGIN
    INSERT INTO qa_fts(rowid, question, answer)
    VALUES (new.id, new.question, new.answer);
END;
CREATE TRIGGER IF NOT EXISTS qa_fts_ad AFTER DELETE ON qa_log BEGIN
    INSERT INTO qa_fts(qa_fts, rowid, question, answer)
    VALUES ('delete', old.id, old.question, old.answer);
END;
"""


def _create_vec_table(conn: sqlite3.Connection, dim: int) -> None:
    conn.execute(
        f"CREATE VIRTUAL TABLE IF NOT EXISTS qa_vec USING vec0("
        f"embedding float[{dim}]"
        f");"
    )


def ensure_schema(
    conn: sqlite3.Connection,
    *,
    vec_loaded: bool,
    embedding_dim: int = HISTORY_VEC_DIM,
) -> None:
    """Create the base table + FTS auxiliary index + triggers
    idempotently. Also creates the vec0 virtual table when
    `vec_loaded` is True (caller passes the flag returned by
    `connect()`).

    Safe to call on every open. Subsequent calls are no-ops thanks to
    the IF NOT EXISTS guards.
    """
    conn.executescript(_SCHEMA_BASE)
    conn.executescript(_SCHEMA_FTS)
    conn.executescript(_FTS_TRIGGERS)

    if vec_loaded:
        _create_vec_table(conn, embedding_dim)

    conn.commit()


def vec_table_exists(conn: sqlite3.Connection) -> bool:
    """True iff `qa_vec` exists in the current db."""
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type IN ('table', 'view') AND name = 'qa_vec'"
    ).fetchone()
    return row is not None

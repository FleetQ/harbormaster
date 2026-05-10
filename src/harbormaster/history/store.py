"""Q&A trajectory store with semantic + lexical recall.

One sqlite db per host, opened lazily and closed via `QAStore.close()`.
Two recall paths share a single base table (`qa_log`):

  * vec path — when an embedding backend returns a non-None vector,
    record() inserts into `qa_log` + `qa_vec`; recall() consults
    `qa_vec` for cosine-similarity ANN.
  * fts path — when the backend returns None (FTS5Backend, or
    fastembed missing), record() relies on the `qa_log` insert
    triggers to populate `qa_fts`; recall() runs an FTS5 MATCH query
    ranked by bm25.

`record()` is best-effort: any exception inside the store is logged
and swallowed at the caller (`_maybe_record_qa`) — the user's MCP
response is already in flight.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import struct
import time
from dataclasses import dataclass
from pathlib import Path

from harbormaster.history.embed import EmbeddingBackend
from harbormaster.history.schema import (
    HISTORY_VEC_DIM,
    EmbeddingMeta,
    connect,
    db_path_for_host,
    drop_and_recreate_vec_table,
    ensure_schema,
    read_embedding_meta,
    update_reembed_resume,
    vec_table_exists,
    write_embedding_meta,
)

logger = logging.getLogger("harbormaster.history.store")


@dataclass(frozen=True)
class QARecord:
    """Input record for QAStore.record()."""

    question: str
    answer: str
    project: str
    host: str
    tool: str
    duration_ms: int | None = None
    cost_cents: int | None = None


@dataclass(frozen=True)
class QAMatch:
    """A recall hit from QAStore.recall()."""

    id: int
    question: str
    answer: str
    project: str
    host: str
    tool: str
    created_at: int
    score: float
    recall_count: int

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "question": self.question,
            "answer": self.answer,
            "project": self.project,
            "host": self.host,
            "tool": self.tool,
            "created_at": self.created_at,
            "score": round(self.score, 4),
            "recall_count": self.recall_count,
        }


def _vec_to_blob(vec: list[float]) -> bytes:
    """Pack a float vector for sqlite-vec (little-endian f32)."""
    return struct.pack(f"{len(vec)}f", *vec)


def _now() -> int:
    return int(time.time())


class QAStore:
    """Per-host Q&A history store.

    Holds a single sqlite connection. Construct via
    `QAStore.open(db_dir, host, embedding_backend)` to get the right
    db file; or pass a path directly for testing.
    """

    def __init__(
        self,
        *,
        conn: sqlite3.Connection,
        embedding_backend: EmbeddingBackend,
        embedding_dim: int = HISTORY_VEC_DIM,
    ) -> None:
        self._conn = conn
        self._embed = embedding_backend
        self._dim = embedding_dim
        self._vec_available = vec_table_exists(conn)

    @classmethod
    def open(
        cls,
        *,
        db_dir: str | Path,
        host: str | None,
        embedding_backend: EmbeddingBackend,
        embedding_dim: int = HISTORY_VEC_DIM,
    ) -> QAStore:
        path = db_path_for_host(db_dir, host)
        conn, vec_loaded = connect(path)
        ensure_schema(conn, vec_loaded=vec_loaded, embedding_dim=embedding_dim)

        # v2.0.0a2: seed embedding_meta on first open and detect drift on
        # subsequent opens. Drift detection alone — no auto-reembed; the
        # operator runs `harbormaster-mcp reembed` explicitly when ready.
        meta = read_embedding_meta(conn)
        signature = embedding_backend.signature
        if meta is None:
            write_embedding_meta(
                conn,
                signature=signature,
                dim=embedding_dim,
                created_at=_now(),
            )
        elif meta.signature != signature or meta.dim != embedding_dim:
            logger.warning(
                "embedding drift detected: stored=%s/dim=%d, configured=%s/dim=%d. "
                "Existing vectors will be served by the old model until you run "
                "`harbormaster-mcp reembed`.",
                meta.signature,
                meta.dim,
                signature,
                embedding_dim,
            )

        return cls(
            conn=conn,
            embedding_backend=embedding_backend,
            embedding_dim=embedding_dim,
        )

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> QAStore:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def record(self, rec: QARecord) -> int | None:
        """Insert one Q&A trajectory. Returns the inserted row id, or
        None if the insert was a no-op (e.g. duplicate question with
        identical answer in last N records).
        """
        try:
            cur = self._conn.execute(
                """
                INSERT INTO qa_log (
                    question, answer, project, host, tool,
                    created_at, duration_ms, cost_cents
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    rec.question,
                    rec.answer,
                    rec.project,
                    rec.host,
                    rec.tool,
                    _now(),
                    rec.duration_ms,
                    rec.cost_cents,
                ),
            )
            row_id = cur.lastrowid
            if row_id is None:
                self._conn.commit()
                return None

            if self._vec_available:
                vec = self._embed.encode(rec.question)
                if vec is not None:
                    if len(vec) != self._dim:
                        logger.warning(
                            "embedding dim mismatch: got %d, expected %d; skipping vec insert",
                            len(vec), self._dim,
                        )
                    else:
                        self._conn.execute(
                            "INSERT INTO qa_vec(rowid, embedding) VALUES (?, ?)",
                            (row_id, _vec_to_blob(vec)),
                        )

            self._conn.commit()
            return row_id
        except sqlite3.Error:
            logger.exception("qa_log insert failed; rolling back")
            self._conn.rollback()
            return None

    def recall(
        self,
        *,
        question: str,
        top_k: int = 5,
        project: str | None = None,
        min_similarity: float = 0.6,
    ) -> list[QAMatch]:
        """Return up to top_k matches ranked by similarity (vec) or
        bm25 (fts). Increments recall_count + last_recalled_at on hit
        rows.
        """
        if not question.strip():
            return []
        if top_k <= 0:
            return []

        vec = self._embed.encode(question) if self._vec_available else None

        if vec is not None and len(vec) == self._dim:
            matches = self._recall_vec(vec, top_k, project, min_similarity)
        else:
            matches = self._recall_fts(question, top_k, project)

        if matches:
            ids = [m.id for m in matches]
            placeholders = ",".join("?" * len(ids))
            self._conn.execute(
                f"""
                UPDATE qa_log
                   SET recall_count = recall_count + 1,
                       last_recalled_at = ?
                 WHERE id IN ({placeholders})
                """,
                (_now(), *ids),
            )
            self._conn.commit()

        return matches

    def _recall_vec(
        self,
        vec: list[float],
        top_k: int,
        project: str | None,
        min_similarity: float,
    ) -> list[QAMatch]:
        # sqlite-vec returns distance ascending; convert to similarity = 1 - distance
        # for cosine on normalized vectors. bge-small embeddings are
        # L2-normalized by fastembed so this is correct out of the box.
        # We over-fetch so the project filter doesn't starve the result.
        fetch_k = max(top_k * 4, top_k + 10)
        rows = self._conn.execute(
            f"""
            SELECT v.rowid AS id,
                   v.distance AS distance,
                   l.question, l.answer, l.project, l.host, l.tool,
                   l.created_at, l.recall_count
              FROM qa_vec AS v
              JOIN qa_log AS l ON l.id = v.rowid
             WHERE v.embedding MATCH ?
               AND k = {fetch_k}
             ORDER BY v.distance ASC
            """,
            (_vec_to_blob(vec),),
        ).fetchall()

        out: list[QAMatch] = []
        for r in rows:
            similarity = 1.0 - float(r["distance"])
            if similarity < min_similarity:
                continue
            if project is not None and r["project"] != project:
                continue
            out.append(
                QAMatch(
                    id=int(r["id"]),
                    question=str(r["question"]),
                    answer=str(r["answer"]),
                    project=str(r["project"]),
                    host=str(r["host"]),
                    tool=str(r["tool"]),
                    created_at=int(r["created_at"]),
                    score=similarity,
                    recall_count=int(r["recall_count"]),
                )
            )
            if len(out) >= top_k:
                break
        return out

    def _recall_fts(
        self,
        question: str,
        top_k: int,
        project: str | None,
    ) -> list[QAMatch]:
        match_query = _fts_match_query(question)
        if not match_query:
            return []

        sql = """
            SELECT l.id, l.question, l.answer, l.project, l.host, l.tool,
                   l.created_at, l.recall_count,
                   bm25(qa_fts) AS score
              FROM qa_fts
              JOIN qa_log AS l ON l.id = qa_fts.rowid
             WHERE qa_fts MATCH ?
        """
        params: list[object] = [match_query]
        if project is not None:
            sql += " AND l.project = ?"
            params.append(project)
        sql += " ORDER BY score ASC LIMIT ?"
        params.append(top_k)

        rows = self._conn.execute(sql, params).fetchall()

        out: list[QAMatch] = []
        for r in rows:
            # bm25 returns lower-is-better; map to a 0..1ish score for
            # consistent UX. score = 1 / (1 + bm25_raw)
            raw = float(r["score"])
            normalized = 1.0 / (1.0 + abs(raw))
            out.append(
                QAMatch(
                    id=int(r["id"]),
                    question=str(r["question"]),
                    answer=str(r["answer"]),
                    project=str(r["project"]),
                    host=str(r["host"]),
                    tool=str(r["tool"]),
                    created_at=int(r["created_at"]),
                    score=normalized,
                    recall_count=int(r["recall_count"]),
                )
            )
        return out

    def prune(self, *, retain_recent_k: int, retain_top_recalled_r: int) -> int:
        """Keep `retain_recent_k` most recent + `retain_top_recalled_r`
        most-recalled rows. Delete the rest. Returns the number of
        rows deleted.
        """
        # SQLite doesn't allow ORDER BY/LIMIT inside a UNION arm without
        # an enclosing SELECT, so we run the two windows separately and
        # union the ids in Python.
        recent = self._conn.execute(
            "SELECT id FROM qa_log ORDER BY created_at DESC LIMIT ?",
            (retain_recent_k,),
        ).fetchall()
        recalled = self._conn.execute(
            "SELECT id FROM qa_log ORDER BY recall_count DESC, created_at DESC LIMIT ?",
            (retain_top_recalled_r,),
        ).fetchall()
        keep_ids = {int(r["id"]) for r in recent} | {int(r["id"]) for r in recalled}

        if not keep_ids:
            return 0

        placeholders = ",".join("?" * len(keep_ids))
        cur = self._conn.execute(
            f"DELETE FROM qa_log WHERE id NOT IN ({placeholders})",
            tuple(keep_ids),
        )
        if self._vec_available:
            self._conn.execute(
                f"DELETE FROM qa_vec WHERE rowid NOT IN ({placeholders})",
                tuple(keep_ids),
            )
        self._conn.commit()
        return int(cur.rowcount or 0)

    def count(self) -> int:
        """Total rows in qa_log. Test/diagnostic helper."""
        row = self._conn.execute("SELECT COUNT(*) AS n FROM qa_log").fetchone()
        return int(row["n"])

    def count_since(self, since_unix_seconds: int) -> int:
        """Return the number of qa_log rows with `created_at >= since`.

        Powers the v8.0.0a5 KPI strip's "recent queries" counter.
        Cheap — uses a covering index on `created_at` (the same
        column the chronological list is ordered by).
        """
        row = self._conn.execute(
            "SELECT COUNT(*) AS n FROM qa_log WHERE created_at >= ?",
            (since_unix_seconds,),
        ).fetchone()
        return int(row["n"]) if row else 0

    def list_recent(
        self,
        *,
        project: str | None = None,
        limit: int = 20,
    ) -> list[QAMatch]:
        """Return the most recent records by created_at desc, optionally
        filtered by project (v2.1.0a6).

        Powers the UI trajectory history view at /api/trajectories.
        Score is set to 1.0 — there's no relevance ranking on a pure
        chronological list, but the QAMatch shape stays uniform so
        callers can render the same way they render `recall()` results.
        """
        if limit <= 0:
            return []
        sql = (
            "SELECT id, question, answer, project, host, tool, "
            "created_at, recall_count FROM qa_log"
        )
        params: list[object] = []
        if project is not None:
            sql += " WHERE project = ?"
            params.append(project)
        # Secondary sort on `id` so same-second inserts have a stable order
        # (created_at is unix-seconds; the underlying autoincrement id is
        # monotonic and breaks the tie deterministically).
        sql += " ORDER BY created_at DESC, id DESC LIMIT ?"
        params.append(limit)
        rows = self._conn.execute(sql, params).fetchall()
        return [
            QAMatch(
                id=int(r["id"]),
                question=str(r["question"]),
                answer=str(r["answer"]),
                project=str(r["project"]),
                host=str(r["host"]),
                tool=str(r["tool"]),
                created_at=int(r["created_at"]),
                score=1.0,
                recall_count=int(r["recall_count"]),
            )
            for r in rows
        ]

    @property
    def vec_available(self) -> bool:
        """True iff this connection can use the vec0 ANN path."""
        return self._vec_available

    # --- v2.0.0a2 embedding upgrade-in-place ----------------------------

    def embedding_meta(self) -> EmbeddingMeta | None:
        """Return the singleton row from `embedding_meta`."""
        return read_embedding_meta(self._conn)

    def has_embedding_drift(self) -> bool:
        """True when the configured embedding backend signature/dim
        differs from the metadata stored in this db."""
        meta = read_embedding_meta(self._conn)
        if meta is None:
            return False
        return meta.signature != self._embed.signature or meta.dim != self._dim

    def reembed(
        self,
        *,
        batch_size: int = 100,
        resume: bool = True,
    ) -> tuple[int, int]:
        """Re-embed every row in qa_log with the currently configured
        backend. Returns `(processed, total)`.

        When `resume=True` (default), starts after
        `embedding_meta.last_reembedded_rowid` so an interrupted run
        can be picked up cleanly. Pass `resume=False` to start from
        scratch (useful when bumping batch_size or after fixing a bad
        run).

        When the stored dim differs from the current dim, `qa_vec` is
        dropped and recreated with the new dim before re-encoding —
        the old vectors are unrecoverable, but they were already
        unusable in the new vector space anyway.

        Updates `embedding_meta.last_reembedded_rowid` after each
        committed batch. Updates the singleton `(signature, dim,
        created_at)` row only after the run completes successfully.
        """
        if not self._vec_available:
            logger.info("reembed: qa_vec unavailable; nothing to do")
            return 0, 0
        if self._embed.dim == 0:
            # Lexical-only backend (FTS5 fallback) — no vectors to write.
            logger.info(
                "reembed: configured backend %s has dim=0; nothing to do",
                self._embed.signature,
            )
            return 0, 0

        meta = read_embedding_meta(self._conn)
        signature = self._embed.signature
        dim_changed = meta is not None and meta.dim != self._dim
        if dim_changed:
            logger.info(
                "reembed: dim change detected (%d → %d); recreating qa_vec",
                meta.dim if meta else 0,
                self._dim,
            )
            drop_and_recreate_vec_table(self._conn, dim=self._dim)
            # Reset resume marker — old vectors are gone.
            update_reembed_resume(self._conn, last_reembedded_rowid=0)

        start_rowid = 0
        if resume and not dim_changed:
            current = read_embedding_meta(self._conn)
            if current is not None:
                start_rowid = current.last_reembedded_rowid

        total_row = self._conn.execute(
            "SELECT COUNT(*) AS n FROM qa_log WHERE id > ?",
            (start_rowid,),
        ).fetchone()
        total = int(total_row["n"])
        if total == 0:
            # Nothing to do — record final meta and clear marker.
            write_embedding_meta(
                self._conn,
                signature=signature,
                dim=self._dim,
                created_at=_now(),
                last_reembedded_rowid=0,
            )
            return 0, 0

        processed = 0
        last_rowid = start_rowid
        while True:
            rows = self._conn.execute(
                "SELECT id, question FROM qa_log WHERE id > ? "
                "ORDER BY id ASC LIMIT ?",
                (last_rowid, batch_size),
            ).fetchall()
            if not rows:
                break
            for row in rows:
                rowid = int(row["id"])
                vec = self._embed.encode(str(row["question"]))
                if vec is not None and len(vec) == self._dim:
                    self._conn.execute(
                        "DELETE FROM qa_vec WHERE rowid = ?", (rowid,)
                    )
                    self._conn.execute(
                        "INSERT INTO qa_vec(rowid, embedding) VALUES (?, ?)",
                        (rowid, _vec_to_blob(vec)),
                    )
                processed += 1
                last_rowid = rowid
            update_reembed_resume(self._conn, last_reembedded_rowid=last_rowid)

        # Mark the run complete: stamp current signature + dim and clear
        # the resume marker so the next reembed starts fresh.
        write_embedding_meta(
            self._conn,
            signature=signature,
            dim=self._dim,
            created_at=_now(),
            last_reembedded_rowid=0,
        )
        return processed, total


# --- internal helpers -----------------------------------------------------


_FTS_SAFE_CHARS = set(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_"
)


def _fts_match_query(text: str) -> str:
    """Build a defensive FTS5 MATCH expression from free text.

    Strategy: tokenize on whitespace, strip non-safe chars per token,
    drop empties, OR-join. Avoids running user input through FTS5
    syntax (no quoted phrases, no NEAR, no column filters) — keeps it
    from blowing up on `(` `)` `:` `*` etc.
    """
    out: list[str] = []
    for raw in text.split():
        cleaned = "".join(c for c in raw if c in _FTS_SAFE_CHARS)
        if cleaned:
            out.append(cleaned)
    if not out:
        return ""
    return " OR ".join(out)


def _record_to_json(rec: QARecord) -> str:
    """Test/diagnostic helper — never used in the hot path."""
    return json.dumps(
        {
            "question": rec.question,
            "answer": rec.answer,
            "project": rec.project,
            "host": rec.host,
            "tool": rec.tool,
        }
    )

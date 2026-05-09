"""Tests for harbormaster.history.store.QAStore.

Two backends exercised:

  * FTS5Backend — bm25 lexical recall (no model download).
  * StubVecBackend — a deterministic 4-dim "embedding" so we can hit
    the vec0 ANN path without pulling fastembed's ONNX model in unit
    tests. fastembed itself is only smoke-tested in test_history_embed.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from harbormaster.history import (
    FTS5Backend,
    QAMatch,
    QARecord,
    QAStore,
)
from harbormaster.history.schema import HISTORY_VEC_DIM


class StubVecBackend:
    """Tiny fake embedding backend for the vec ANN path.

    Encodes a string into a length-4 vector by counting occurrences of
    'a', 'b', 'c', 'd' (case-insensitive). Deterministic, fast,
    extension-friendly.
    """

    name = "stub"
    dim = 4

    def encode(self, text: str) -> list[float] | None:
        s = text.lower()
        return [
            float(s.count("a")),
            float(s.count("b")),
            float(s.count("c")),
            float(s.count("d")),
        ]


def _open(tmp_path: Path, *, vec: bool = False) -> QAStore:
    if vec:
        return QAStore.open(
            db_dir=tmp_path,
            host=None,
            embedding_backend=StubVecBackend(),
            embedding_dim=4,
        )
    return QAStore.open(
        db_dir=tmp_path,
        host=None,
        embedding_backend=FTS5Backend(),
        embedding_dim=HISTORY_VEC_DIM,
    )


def _record(question: str, answer: str = "stub answer", project: str = "alpha") -> QARecord:
    return QARecord(
        question=question,
        answer=answer,
        project=project,
        host="local",
        tool="ask_project",
    )


# --- record path -----------------------------------------------------------


def test_record_returns_row_id_for_first_insert(tmp_path: Path):
    store = _open(tmp_path)
    try:
        rid = store.record(_record("hello"))
        assert rid == 1
        assert store.count() == 1
    finally:
        store.close()


def test_record_writes_all_fields(tmp_path: Path):
    store = _open(tmp_path)
    try:
        rec = QARecord(
            question="what is 2+2?",
            answer="4",
            project="math",
            host="friday",
            tool="ask_project",
            duration_ms=123,
            cost_cents=2,
        )
        store.record(rec)
        row = store._conn.execute("SELECT * FROM qa_log").fetchone()
        assert row["question"] == "what is 2+2?"
        assert row["answer"] == "4"
        assert row["project"] == "math"
        assert row["host"] == "friday"
        assert row["tool"] == "ask_project"
        assert row["duration_ms"] == 123
        assert row["cost_cents"] == 2
        assert row["recall_count"] == 0
        assert row["last_recalled_at"] is None
        assert row["created_at"] > 0
    finally:
        store.close()


# --- recall path: FTS5 -----------------------------------------------------


def test_recall_fts_returns_lexical_match(tmp_path: Path):
    store = _open(tmp_path)
    try:
        store.record(_record("How does authentication work?", "JWT-based"))
        store.record(_record("How does pagination work?", "cursor-based"))

        matches = store.recall(question="authentication")
        assert len(matches) == 1
        assert matches[0].project == "alpha"
        assert "authentication" in matches[0].question.lower()
        assert matches[0].score > 0
    finally:
        store.close()


def test_recall_filters_by_project(tmp_path: Path):
    store = _open(tmp_path)
    try:
        store.record(_record("How does authentication work?", "x", project="alpha"))
        store.record(_record("How does authentication work?", "y", project="beta"))

        out = store.recall(question="authentication", project="beta")
        assert len(out) == 1
        assert out[0].project == "beta"
    finally:
        store.close()


def test_recall_handles_empty_question(tmp_path: Path):
    store = _open(tmp_path)
    try:
        assert store.recall(question="   ") == []
        assert store.recall(question="") == []
    finally:
        store.close()


def test_recall_returns_empty_when_top_k_zero(tmp_path: Path):
    store = _open(tmp_path)
    try:
        store.record(_record("hello world"))
        assert store.recall(question="hello", top_k=0) == []
    finally:
        store.close()


def test_recall_increments_recall_count(tmp_path: Path):
    store = _open(tmp_path)
    try:
        store.record(_record("how does X work?"))
        before = store._conn.execute("SELECT recall_count, last_recalled_at FROM qa_log").fetchone()
        assert before["recall_count"] == 0
        assert before["last_recalled_at"] is None

        out = store.recall(question="how does X work?")
        assert out

        after = store._conn.execute("SELECT recall_count, last_recalled_at FROM qa_log").fetchone()
        assert after["recall_count"] == 1
        assert after["last_recalled_at"] is not None
    finally:
        store.close()


def test_recall_handles_punctuation_and_special_chars(tmp_path: Path):
    """User questions often contain `(`, `)`, `:`, `*`. Must not crash FTS5."""
    store = _open(tmp_path)
    try:
        store.record(_record("How do I parse foo(bar): baz?"))
        # All-special-char input → no MATCH terms → empty result, not exception
        assert store.recall(question="(((:::***)))") == []
        # Punctuated normal input → match
        out = store.recall(question="How do I (parse) foo:bar?")
        assert len(out) == 1
    finally:
        store.close()


# --- recall path: vec ------------------------------------------------------


def test_recall_vec_returns_nearest_by_distance(tmp_path: Path):
    store = _open(tmp_path, vec=True)
    try:
        # encode("aaaa") = [4,0,0,0], encode("bbbb") = [0,4,0,0]
        store.record(_record("aaaa", "answer-a"))
        store.record(_record("bbbb", "answer-b"))
        store.record(_record("aaab", "answer-ab"))

        out = store.recall(question="aaaa", min_similarity=0.0)
        assert out
        # Best match should be the exact "aaaa" question.
        assert out[0].answer == "answer-a"
    finally:
        store.close()


def test_recall_vec_filters_below_min_similarity(tmp_path: Path):
    store = _open(tmp_path, vec=True)
    try:
        store.record(_record("aaaa"))
        store.record(_record("dddd"))
        out = store.recall(question="aaaa", min_similarity=0.99)
        # "dddd" is orthogonal → similarity ≈ 0 → filtered.
        assert all(m.answer != "stub answer" or m.question == "aaaa" for m in out)
    finally:
        store.close()


def test_vec_available_property(tmp_path: Path):
    fts_store = _open(tmp_path / "fts")
    vec_store = _open(tmp_path / "vec", vec=True)
    try:
        # Both create vec table because sqlite-vec is loaded; the
        # difference is only which path recall takes (driven by encode()).
        assert fts_store.vec_available is True
        assert vec_store.vec_available is True
    finally:
        fts_store.close()
        vec_store.close()


# --- prune ----------------------------------------------------------------


def test_prune_keeps_most_recent(tmp_path: Path):
    store = _open(tmp_path)
    try:
        for i in range(10):
            store.record(_record(f"q{i}"))
        deleted = store.prune(retain_recent_k=3, retain_top_recalled_r=0)
        assert deleted == 7
        assert store.count() == 3
        rows = store._conn.execute(
            "SELECT question FROM qa_log ORDER BY id DESC"
        ).fetchall()
        assert [r["question"] for r in rows] == ["q9", "q8", "q7"]
    finally:
        store.close()


def test_prune_keeps_top_recalled_even_if_old(tmp_path: Path):
    store = _open(tmp_path)
    try:
        for i in range(10):
            store.record(_record(f"q{i}"))
        # Bump recall count on q0
        store._conn.execute(
            "UPDATE qa_log SET recall_count = 99 WHERE question = 'q0'"
        )
        store._conn.commit()

        store.prune(retain_recent_k=3, retain_top_recalled_r=1)
        rows = store._conn.execute(
            "SELECT question FROM qa_log ORDER BY id"
        ).fetchall()
        questions = [r["question"] for r in rows]
        assert "q0" in questions  # kept by recall_count
        assert "q9" in questions  # kept by recency
    finally:
        store.close()


def test_prune_with_empty_table_is_safe(tmp_path: Path):
    store = _open(tmp_path)
    try:
        deleted = store.prune(retain_recent_k=10, retain_top_recalled_r=10)
        assert deleted == 0
    finally:
        store.close()


def test_prune_also_cleans_vec_rows(tmp_path: Path):
    store = _open(tmp_path, vec=True)
    try:
        for i in range(5):
            store.record(_record(f"q{i}"))
        log_before = store._conn.execute("SELECT COUNT(*) AS n FROM qa_log").fetchone()["n"]
        vec_before = store._conn.execute("SELECT COUNT(*) AS n FROM qa_vec").fetchone()["n"]
        assert log_before == 5
        assert vec_before == 5

        store.prune(retain_recent_k=2, retain_top_recalled_r=0)

        log_after = store._conn.execute("SELECT COUNT(*) AS n FROM qa_log").fetchone()["n"]
        vec_after = store._conn.execute("SELECT COUNT(*) AS n FROM qa_vec").fetchone()["n"]
        assert log_after == 2
        assert vec_after == 2
    finally:
        store.close()


# --- QAMatch.to_dict ------------------------------------------------------


def test_qa_match_to_dict_round_trip():
    m = QAMatch(
        id=1, question="q", answer="a", project="alpha",
        host="local", tool="ask_project", created_at=1234,
        score=0.987654, recall_count=3,
    )
    d = m.to_dict()
    assert d["id"] == 1
    assert d["question"] == "q"
    assert d["score"] == pytest.approx(0.9877, abs=1e-4)
    assert d["recall_count"] == 3

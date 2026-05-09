"""Tests for harbormaster.history.schema (sqlite-vec + FTS5 schema)."""
from __future__ import annotations

import sqlite3
from pathlib import Path

from harbormaster.history.schema import (
    HISTORY_VEC_DIM,
    _sanitize_host,
    connect,
    db_path_for_host,
    ensure_schema,
    vec_table_exists,
)


def test_sanitize_host_local_when_none():
    assert _sanitize_host(None) == "local"
    assert _sanitize_host("") == "local"


def test_sanitize_host_replaces_unsafe_chars():
    assert _sanitize_host("friday.local") == "friday.local"
    assert _sanitize_host("user@host:22") == "user_host_22"
    assert _sanitize_host("../etc/passwd") == ".._etc_passwd"


def test_db_path_for_host_uses_host_in_filename(tmp_path: Path):
    p = db_path_for_host(tmp_path, "friday")
    assert p.parent == tmp_path
    assert p.name == "qa_friday.db"


def test_db_path_for_host_local_when_none(tmp_path: Path):
    p = db_path_for_host(tmp_path, None)
    assert p.name == "qa_local.db"


def test_connect_creates_parent_dir(tmp_path: Path):
    target = tmp_path / "nested" / "x.db"
    conn, _ = connect(target)
    try:
        assert target.parent.is_dir()
        assert isinstance(conn, sqlite3.Connection)
    finally:
        conn.close()


def test_connect_returns_vec_loaded_flag(tmp_path: Path):
    """sqlite-vec is in the dev extra so it should load on the test runner."""
    conn, vec_loaded = connect(tmp_path / "x.db")
    try:
        assert vec_loaded is True
    finally:
        conn.close()


def test_ensure_schema_creates_qa_log_and_fts(tmp_path: Path):
    conn, vec_loaded = connect(tmp_path / "x.db")
    try:
        ensure_schema(conn, vec_loaded=vec_loaded)
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type IN ('table', 'view')"
        ).fetchall()
        names = {r["name"] for r in rows}
        assert "qa_log" in names
        assert "qa_fts" in names
        if vec_loaded:
            assert "qa_vec" in names
    finally:
        conn.close()


def test_ensure_schema_is_idempotent(tmp_path: Path):
    """Calling ensure_schema twice should not raise (IF NOT EXISTS guards)."""
    db = tmp_path / "x.db"
    conn1, vl1 = connect(db)
    ensure_schema(conn1, vec_loaded=vl1)
    conn1.close()

    conn2, vl2 = connect(db)
    # Must not raise
    ensure_schema(conn2, vec_loaded=vl2)
    conn2.close()


def test_qa_log_columns_match_design(tmp_path: Path):
    conn, vl = connect(tmp_path / "x.db")
    try:
        ensure_schema(conn, vec_loaded=vl)
        cols = {r[1] for r in conn.execute("PRAGMA table_info(qa_log)")}
        assert {
            "id", "question", "answer", "project", "host", "tool",
            "created_at", "duration_ms", "cost_cents",
            "recall_count", "last_recalled_at",
        } <= cols
    finally:
        conn.close()


def test_vec_table_exists_after_ensure_schema(tmp_path: Path):
    conn, vl = connect(tmp_path / "x.db")
    try:
        ensure_schema(conn, vec_loaded=vl)
        if vl:
            assert vec_table_exists(conn) is True
        else:
            assert vec_table_exists(conn) is False
    finally:
        conn.close()


def test_vec_dim_default_is_384():
    """Default matches BAAI/bge-small-en-v1.5 output dim."""
    assert HISTORY_VEC_DIM == 384

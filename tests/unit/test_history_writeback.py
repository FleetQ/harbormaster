"""Tests for the _maybe_record_qa integration into run_backend.

Mirrors test_memory_writeback.py's gating tests for the FleetQ
hook — three-gate opt-in, silent on failure, never propagates.
"""
from __future__ import annotations

from pathlib import Path

from harbormaster.config import HarbormasterConfig, HistoryConfig
from harbormaster.history import FTS5Backend, QAStore
from harbormaster.tools import _helpers


def _config(tmp_path: Path, *, enabled: bool = True, **history_kw) -> HarbormasterConfig:
    return HarbormasterConfig(
        history=HistoryConfig(
            enabled=enabled,
            embedding_backend="fts5",
            db_dir=str(tmp_path),
            **history_kw,
        )
    )


def _open(tmp_path: Path, host: str | None = None) -> QAStore:
    return QAStore.open(
        db_dir=tmp_path,
        host=host,
        embedding_backend=FTS5Backend(),
    )


def test_maybe_record_skips_when_history_disabled(tmp_path: Path):
    config = _config(tmp_path, enabled=False)
    _helpers._maybe_record_qa(
        config=config, project_name="alpha", host=None,
        prompt="q", answer="a", tool="ask_project", duration_ms=1,
    )
    # No db file should have been created.
    assert list(tmp_path.iterdir()) == []


def test_maybe_record_skips_when_per_tool_disabled(tmp_path: Path):
    config = _config(tmp_path, log_ask_project=False)
    _helpers._maybe_record_qa(
        config=config, project_name="alpha", host=None,
        prompt="q", answer="a", tool="ask_project", duration_ms=1,
    )
    assert list(tmp_path.iterdir()) == []


def test_maybe_record_writes_when_enabled(tmp_path: Path):
    config = _config(tmp_path)
    _helpers._maybe_record_qa(
        config=config, project_name="alpha", host=None,
        prompt="how does X work?", answer="like this",
        tool="ask_project", duration_ms=1234,
    )
    store = _open(tmp_path)
    try:
        assert store.count() == 1
        row = store._conn.execute("SELECT * FROM qa_log").fetchone()
        assert row["question"] == "how does X work?"
        assert row["answer"] == "like this"
        assert row["project"] == "alpha"
        assert row["host"] == "local"
        assert row["tool"] == "ask_project"
        assert row["duration_ms"] == 1234
    finally:
        store.close()


def test_maybe_record_passes_host_through(tmp_path: Path):
    config = _config(tmp_path)
    _helpers._maybe_record_qa(
        config=config, project_name="alpha", host="friday",
        prompt="q", answer="a", tool="delegate_task", duration_ms=1,
    )
    store = _open(tmp_path, host="friday")
    try:
        assert store.count() == 1
        row = store._conn.execute("SELECT host, tool FROM qa_log").fetchone()
        assert row["host"] == "friday"
        assert row["tool"] == "delegate_task"
    finally:
        store.close()


def test_maybe_record_swallows_unexpected_exception(tmp_path: Path, monkeypatch):
    """If the store blows up internally, _maybe_record_qa must NOT
    propagate — the user's MCP response is already in flight."""
    config = _config(tmp_path)

    class ExplodingStore:
        def record(self, *_args, **_kw):
            raise RuntimeError("boom")

        def prune(self, *_args, **_kw):
            raise RuntimeError("boom2")

        def close(self):
            pass

    monkeypatch.setattr(
        "harbormaster.history.QAStore.open",
        classmethod(lambda *a, **kw: ExplodingStore()),
    )

    # MUST NOT raise:
    _helpers._maybe_record_qa(
        config=config, project_name="alpha", host=None,
        prompt="q", answer="a", tool="ask_project", duration_ms=1,
    )


def test_maybe_record_per_tool_flags_independent(tmp_path: Path):
    """Disabling one tool's logging doesn't affect another tool."""
    config = _config(tmp_path, log_ask_project=False, log_delegate_task=True)

    _helpers._maybe_record_qa(
        config=config, project_name="alpha", host=None,
        prompt="q1", answer="a1", tool="ask_project", duration_ms=1,
    )
    _helpers._maybe_record_qa(
        config=config, project_name="alpha", host=None,
        prompt="q2", answer="a2", tool="delegate_task", duration_ms=1,
    )

    store = _open(tmp_path)
    try:
        rows = store._conn.execute("SELECT question, tool FROM qa_log").fetchall()
        # Only the delegate_task call landed.
        assert len(rows) == 1
        assert rows[0]["tool"] == "delegate_task"
    finally:
        store.close()

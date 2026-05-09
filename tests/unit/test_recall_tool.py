"""Tests for the recall_qa MCP tool surface."""
from __future__ import annotations

from pathlib import Path

from harbormaster.config import HarbormasterConfig, HistoryConfig
from harbormaster.server import build_server


def _tools_by_name(mcp):
    return {t.name: t for t in mcp._tool_manager.list_tools()}


def _config(tmp_path: Path, *, enabled: bool = True, backend: str = "fts5") -> HarbormasterConfig:
    return HarbormasterConfig(
        history=HistoryConfig(
            enabled=enabled,
            embedding_backend=backend,  # type: ignore[arg-type]
            db_dir=str(tmp_path),
        )
    )


def test_recall_qa_registered_among_tools():
    mcp = build_server(HarbormasterConfig())
    assert "recall_qa" in _tools_by_name(mcp)


def test_recall_qa_returns_disabled_when_history_off(tmp_path: Path):
    mcp = build_server(_config(tmp_path, enabled=False))
    fn = _tools_by_name(mcp)["recall_qa"].fn
    out = fn(question="anything")
    assert out["enabled"] is False
    assert out["matches"] == []
    assert "disabled" in out["message"]


def test_recall_qa_returns_empty_matches_on_empty_store(tmp_path: Path):
    mcp = build_server(_config(tmp_path))
    fn = _tools_by_name(mcp)["recall_qa"].fn
    out = fn(question="hello")
    assert out["enabled"] is True
    assert out["backend"] == "fts5"
    assert out["matches"] == []
    assert out["host"] == "local"


def test_recall_qa_returns_matches_after_record(tmp_path: Path):
    """End-to-end: open a store directly, write one record, then call
    the MCP tool and confirm it returns the match."""
    from harbormaster.history import FTS5Backend, QARecord, QAStore

    config = _config(tmp_path)
    # Pre-seed the same db file the tool will open.
    store = QAStore.open(
        db_dir=config.history.db_dir,
        host=None,
        embedding_backend=FTS5Backend(),
    )
    try:
        store.record(
            QARecord(
                question="How does authentication work?",
                answer="JWT-based, see auth.md",
                project="myapp",
                host="local",
                tool="ask_project",
            )
        )
    finally:
        store.close()

    mcp = build_server(config)
    fn = _tools_by_name(mcp)["recall_qa"].fn
    out = fn(question="authentication")

    assert out["enabled"] is True
    assert len(out["matches"]) == 1
    m = out["matches"][0]
    assert m["project"] == "myapp"
    assert m["host"] == "local"
    assert m["tool"] == "ask_project"
    assert "JWT" in m["answer"]


def test_recall_qa_filters_by_project(tmp_path: Path):
    from harbormaster.history import FTS5Backend, QARecord, QAStore

    config = _config(tmp_path)
    store = QAStore.open(
        db_dir=config.history.db_dir,
        host=None,
        embedding_backend=FTS5Backend(),
    )
    try:
        store.record(QARecord(
            question="how does X work?", answer="alpha",
            project="alpha", host="local", tool="ask_project",
        ))
        store.record(QARecord(
            question="how does X work?", answer="beta",
            project="beta", host="local", tool="ask_project",
        ))
    finally:
        store.close()

    mcp = build_server(config)
    fn = _tools_by_name(mcp)["recall_qa"].fn
    out = fn(question="X", project="beta")
    assert len(out["matches"]) == 1
    assert out["matches"][0]["project"] == "beta"


def test_recall_qa_uses_default_top_k_from_config(tmp_path: Path):
    from harbormaster.history import FTS5Backend, QARecord, QAStore

    config = HarbormasterConfig(
        history=HistoryConfig(
            enabled=True,
            embedding_backend="fts5",
            db_dir=str(tmp_path),
            default_top_k=2,
        )
    )
    store = QAStore.open(
        db_dir=config.history.db_dir,
        host=None,
        embedding_backend=FTS5Backend(),
    )
    try:
        for i in range(5):
            store.record(QARecord(
                question=f"how does feature{i} work?",
                answer=f"answer-{i}", project="alpha",
                host="local", tool="ask_project",
            ))
    finally:
        store.close()

    mcp = build_server(config)
    fn = _tools_by_name(mcp)["recall_qa"].fn
    out = fn(question="feature1 feature2 feature3 feature4")
    # Capped at default_top_k = 2
    assert len(out["matches"]) <= 2

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


# --- v2.0.0a6 cross-host recall aggregation -----------------------------


def _seed_host_store(
    config: HarbormasterConfig, host: str | None, records: list[tuple[str, str, str]]
) -> None:
    """Seed the per-host store with `(question, answer, project)` records."""
    from harbormaster.history import FTS5Backend, QARecord, QAStore

    store = QAStore.open(
        db_dir=config.history.db_dir,
        host=host,
        embedding_backend=FTS5Backend(),
    )
    try:
        for question, answer, project in records:
            store.record(
                QARecord(
                    question=question,
                    answer=answer,
                    project=project,
                    host=host if host is not None else "local",
                    tool="ask_project",
                )
            )
    finally:
        store.close()


def test_recall_qa_host_all_fans_out_across_local_and_hosts(tmp_path: Path):
    from harbormaster.config import HostConfig

    config = HarbormasterConfig(
        history=HistoryConfig(
            enabled=True,
            embedding_backend="fts5",
            db_dir=str(tmp_path),
        ),
        hosts={
            "friday": HostConfig(ssh_host="friday.local"),
            "jarvis": HostConfig(ssh_host="jarvis.local"),
        },
    )
    _seed_host_store(config, None, [("local hint about authentication", "local-answer", "p1")])
    _seed_host_store(config, "friday", [("friday hint about authentication", "friday-answer", "p1")])
    _seed_host_store(config, "jarvis", [("jarvis hint about authentication", "jarvis-answer", "p1")])

    mcp = build_server(config)
    fn = _tools_by_name(mcp)["recall_qa"].fn
    out = fn(question="authentication", host="all", top_k=10)

    assert out["enabled"] is True
    assert out["host"] == "all"
    assert "hosts_searched" in out
    assert set(out["hosts_searched"]) == {"local", "friday", "jarvis"}
    assert len(out["matches"]) == 3
    hosts_in_matches = {m["host"] for m in out["matches"]}
    assert hosts_in_matches == {"local", "friday", "jarvis"}


def test_recall_qa_host_all_score_sorts_across_hosts(tmp_path: Path):
    """Cross-host results must be ordered by score descending."""
    from harbormaster.config import HostConfig

    config = HarbormasterConfig(
        history=HistoryConfig(
            enabled=True,
            embedding_backend="fts5",
            db_dir=str(tmp_path),
        ),
        hosts={"friday": HostConfig(ssh_host="friday.local")},
    )
    _seed_host_store(config, None, [("authentication note", "weak", "p1")])
    _seed_host_store(
        config, "friday", [("authentication authorization session", "strong", "p1")]
    )

    mcp = build_server(config)
    fn = _tools_by_name(mcp)["recall_qa"].fn
    out = fn(question="authentication authorization session", host="all", top_k=10)

    matches = out["matches"]
    assert len(matches) == 2
    # Both hosts represented; merged result must be non-increasing in score.
    scores = [m["score"] for m in matches]
    assert scores == sorted(scores, reverse=True)


def test_recall_qa_host_all_caps_merged_results_at_top_k(tmp_path: Path):
    from harbormaster.config import HostConfig

    config = HarbormasterConfig(
        history=HistoryConfig(
            enabled=True,
            embedding_backend="fts5",
            db_dir=str(tmp_path),
        ),
        hosts={"friday": HostConfig(ssh_host="friday.local")},
    )
    _seed_host_store(
        config, None, [(f"feature{i} authentication", f"a-{i}", "p1") for i in range(5)]
    )
    _seed_host_store(
        config, "friday", [(f"friday feature{i} authentication", f"f-{i}", "p1") for i in range(5)]
    )

    mcp = build_server(config)
    fn = _tools_by_name(mcp)["recall_qa"].fn
    out = fn(question="authentication", host="all", top_k=4)
    assert len(out["matches"]) <= 4


def test_recall_qa_host_all_with_no_hosts_configured_searches_local(tmp_path: Path):
    config = HarbormasterConfig(
        history=HistoryConfig(
            enabled=True,
            embedding_backend="fts5",
            db_dir=str(tmp_path),
        ),
    )
    _seed_host_store(config, None, [("authentication on local", "ans", "p1")])

    mcp = build_server(config)
    fn = _tools_by_name(mcp)["recall_qa"].fn
    out = fn(question="authentication", host="all", top_k=5)
    assert out["host"] == "all"
    assert out["hosts_searched"] == ["local"]
    assert len(out["matches"]) == 1


def test_recall_qa_host_all_isolates_failures_per_host(
    tmp_path: Path, monkeypatch
):
    """If one host's store fails to open, the others still aggregate
    and the response surfaces an `errors` map for the broken host."""
    from harbormaster.config import HostConfig

    config = HarbormasterConfig(
        history=HistoryConfig(
            enabled=True,
            embedding_backend="fts5",
            db_dir=str(tmp_path),
        ),
        hosts={"broken": HostConfig(ssh_host="broken.local")},
    )
    _seed_host_store(config, None, [("authentication on local", "ans", "p1")])

    # Patch QAStore.open to raise for "broken" but pass through for others.
    from harbormaster.history import QAStore

    real_open = QAStore.open

    def flaky_open(*, host=None, **kwargs):
        if host == "broken":
            raise RuntimeError("simulated open failure")
        return real_open(host=host, **kwargs)

    monkeypatch.setattr(QAStore, "open", flaky_open)

    mcp = build_server(config)
    fn = _tools_by_name(mcp)["recall_qa"].fn
    out = fn(question="authentication", host="all", top_k=5)

    assert out["host"] == "all"
    assert "errors" in out
    assert "broken" in out["errors"]
    assert "broken" not in {m["host"] for m in out["matches"]}
    # Local hit still landed.
    assert any(m["host"] == "local" for m in out["matches"])

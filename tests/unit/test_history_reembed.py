"""Tests for the v2.0.0a2 embedding upgrade-in-place flow.

Covers:
- `embedding_meta` row seeding on first open + drift detection on flips
- `QAStore.reembed()` batch + resume semantics
- `harbormaster-mcp reembed` CLI dispatch via `harbormaster.history.cli`
"""
from __future__ import annotations

from pathlib import Path

import pytest

from harbormaster.config import HarbormasterConfig
from harbormaster.history import FTS5Backend, QARecord, QAStore
from harbormaster.history.schema import (
    HISTORY_VEC_DIM,
    EmbeddingMeta,
    read_embedding_meta,
)


class StubVecBackendV1:
    name = "stub"
    dim = 4

    @property
    def signature(self) -> str:
        return "stub/v1"

    def encode(self, text: str) -> list[float] | None:
        s = text.lower()
        return [
            float(s.count("a")),
            float(s.count("b")),
            float(s.count("c")),
            float(s.count("d")),
        ]


class StubVecBackendV2:
    """Same dim as V1 but a different signature — signature drift only."""

    name = "stub"
    dim = 4

    @property
    def signature(self) -> str:
        return "stub/v2"

    def encode(self, text: str) -> list[float] | None:
        s = text.lower()
        return [
            float(s.count("z")),
            float(s.count("y")),
            float(s.count("x")),
            float(s.count("w")),
        ]


class StubVecBackendV3:
    """Different dim from V1 — exercises the qa_vec recreate path."""

    name = "stub"
    dim = 6

    @property
    def signature(self) -> str:
        return "stub/v3"

    def encode(self, text: str) -> list[float] | None:
        s = text.lower()
        return [
            float(s.count("a")),
            float(s.count("b")),
            float(s.count("c")),
            float(s.count("d")),
            float(s.count("e")),
            float(s.count("f")),
        ]


def _open_v1(tmp_path: Path) -> QAStore:
    return QAStore.open(
        db_dir=tmp_path,
        host=None,
        embedding_backend=StubVecBackendV1(),
        embedding_dim=4,
    )


# --- embedding_meta seeding ---------------------------------------------


def test_embedding_meta_seeded_on_first_open(tmp_path: Path):
    store = _open_v1(tmp_path)
    meta = store.embedding_meta()
    assert meta is not None
    assert meta.signature == "stub/v1"
    assert meta.dim == 4
    assert meta.last_reembedded_rowid == 0
    assert meta.created_at > 0
    store.close()


def test_no_drift_when_signature_matches(tmp_path: Path):
    _open_v1(tmp_path).close()
    store = _open_v1(tmp_path)
    assert store.has_embedding_drift() is False
    store.close()


def test_drift_detected_on_signature_change(tmp_path: Path):
    _open_v1(tmp_path).close()
    store = QAStore.open(
        db_dir=tmp_path,
        host=None,
        embedding_backend=StubVecBackendV2(),
        embedding_dim=4,
    )
    assert store.has_embedding_drift() is True
    store.close()


def test_drift_detected_on_dim_change(tmp_path: Path):
    _open_v1(tmp_path).close()
    store = QAStore.open(
        db_dir=tmp_path,
        host=None,
        embedding_backend=StubVecBackendV3(),
        embedding_dim=6,
    )
    assert store.has_embedding_drift() is True
    store.close()


def test_open_does_not_overwrite_existing_meta(tmp_path: Path):
    """Subsequent opens must not bump created_at or reset state."""
    store1 = _open_v1(tmp_path)
    meta1 = store1.embedding_meta()
    assert meta1 is not None
    store1.close()

    store2 = _open_v1(tmp_path)
    meta2 = store2.embedding_meta()
    assert meta2 == meta1
    store2.close()


# --- reembed semantics --------------------------------------------------


def _record(store: QAStore, q: str, a: str = "answer") -> int | None:
    return store.record(
        QARecord(
            question=q, answer=a, project="p", host="local", tool="ask_project"
        )
    )


def test_reembed_no_op_when_qa_vec_unavailable(tmp_path: Path):
    """FTS5 backend has no qa_vec; reembed must short-circuit cleanly."""
    store = QAStore.open(
        db_dir=tmp_path,
        host=None,
        embedding_backend=FTS5Backend(),
        embedding_dim=HISTORY_VEC_DIM,
    )
    _record(store, "hello")
    processed, total = store.reembed(batch_size=10)
    assert processed == 0
    assert total == 0
    store.close()


def test_reembed_processes_all_rows_when_no_drift(tmp_path: Path):
    pytest.importorskip("sqlite_vec")
    store = _open_v1(tmp_path)
    if not store.vec_available:
        pytest.skip("sqlite-vec extension unavailable")
    for i in range(5):
        _record(store, f"question {i}")

    # Manually mark embedding_meta as needing rework — to force iteration
    # through every row (signature unchanged but resume=False).
    processed, total = store.reembed(batch_size=2, resume=False)
    assert processed == 5
    assert total == 5

    meta = store.embedding_meta()
    assert meta is not None
    # Resume marker reset to 0 on completion.
    assert meta.last_reembedded_rowid == 0
    store.close()


def test_reembed_resume_skips_completed_rows(tmp_path: Path):
    pytest.importorskip("sqlite_vec")
    store = _open_v1(tmp_path)
    if not store.vec_available:
        pytest.skip("sqlite-vec extension unavailable")
    for i in range(3):
        _record(store, f"q{i}")

    # Simulate an interrupted run: first batch processed, marker stuck.
    from harbormaster.history.schema import update_reembed_resume

    rows = store._conn.execute(  # type: ignore[attr-defined]
        "SELECT id FROM qa_log ORDER BY id"
    ).fetchall()
    midpoint = int(rows[1]["id"])
    update_reembed_resume(store._conn, last_reembedded_rowid=midpoint)  # type: ignore[attr-defined]

    processed, total = store.reembed(batch_size=10, resume=True)
    # Only the 3rd row remains pending.
    assert processed == 1
    assert total == 1
    store.close()


def test_reembed_recreates_qa_vec_on_dim_change(tmp_path: Path):
    """When the configured dim differs from the stored dim, qa_vec must
    be dropped and recreated to match the new dim."""
    pytest.importorskip("sqlite_vec")
    store_v1 = _open_v1(tmp_path)
    if not store_v1.vec_available:
        pytest.skip("sqlite-vec extension unavailable")
    for i in range(3):
        _record(store_v1, f"row {i}")
    store_v1.close()

    store_v3 = QAStore.open(
        db_dir=tmp_path,
        host=None,
        embedding_backend=StubVecBackendV3(),
        embedding_dim=6,
    )
    assert store_v3.has_embedding_drift() is True
    processed, total = store_v3.reembed(batch_size=2)
    assert processed == 3
    assert total == 3

    meta = store_v3.embedding_meta()
    assert meta is not None
    assert meta.signature == "stub/v3"
    assert meta.dim == 6
    assert meta.last_reembedded_rowid == 0
    assert store_v3.has_embedding_drift() is False
    store_v3.close()


def test_reembed_updates_meta_only_after_completion(tmp_path: Path):
    """The (signature, dim) row must NOT be advanced mid-run — otherwise
    a crash would silently leave drift undetected on next open."""
    pytest.importorskip("sqlite_vec")
    store = _open_v1(tmp_path)
    if not store.vec_available:
        pytest.skip("sqlite-vec extension unavailable")
    for i in range(3):
        _record(store, f"q{i}")

    # Simulate a crash by capturing meta after each batch via a custom batch.
    import harbormaster.history.schema as schema_mod

    captured: list[EmbeddingMeta] = []
    real_update = schema_mod.update_reembed_resume

    def spy_update_resume(conn, *, last_reembedded_rowid: int) -> None:
        real_update(conn, last_reembedded_rowid=last_reembedded_rowid)
        m = read_embedding_meta(conn)
        if m is not None:
            captured.append(m)

    schema_mod.update_reembed_resume = spy_update_resume  # type: ignore[assignment]
    try:
        # Switch to a different signature to force a real update at the end.
        store_v2 = QAStore.open(
            db_dir=tmp_path,
            host=None,
            embedding_backend=StubVecBackendV2(),
            embedding_dim=4,
        )
        if not store_v2.vec_available:
            pytest.skip("sqlite-vec extension unavailable")
        store_v2.reembed(batch_size=1)
        # Mid-run captures must still show the OLD signature
        # (only last_reembedded_rowid advances).
        for m in captured[:-1]:  # exclude post-completion sync
            assert m.signature == "stub/v1"
        store_v2.close()
    finally:
        schema_mod.update_reembed_resume = real_update  # type: ignore[assignment]
    store.close()


# --- CLI -----------------------------------------------------------------


def test_reembed_cli_help():
    from harbormaster.history.cli import _build_parser

    parser = _build_parser()
    # Exercise that the parser builds without raising and accepts the
    # documented flags.
    ns = parser.parse_args(
        ["--host", "friday", "--batch-size", "50", "--no-resume", "--dry-run"]
    )
    assert ns.host == "friday"
    assert ns.batch_size == 50
    assert ns.no_resume is True
    assert ns.dry_run is True


def test_reembed_cli_rejects_unknown_host(tmp_path: Path, monkeypatch, capsys):
    from harbormaster.history.cli import main as cli_main

    config = HarbormasterConfig()
    monkeypatch.setattr("harbormaster.history.cli.load_config", lambda _p: config)

    with pytest.raises(SystemExit) as exc:
        cli_main(["--host", "ghost-host"])
    msg = str(exc.value)
    assert "ghost-host" in msg


def test_reembed_cli_dry_run_does_not_modify_store(tmp_path: Path, monkeypatch, capsys):
    pytest.importorskip("sqlite_vec")
    from harbormaster.history.cli import main as cli_main

    # Stand up a store with rows so the CLI has something to report on.
    store = _open_v1(tmp_path)
    if not store.vec_available:
        store.close()
        pytest.skip("sqlite-vec extension unavailable")
    for i in range(2):
        _record(store, f"q{i}")
    meta_before = store.embedding_meta()
    store.close()

    config = HarbormasterConfig()
    config.history.db_dir = str(tmp_path)
    config.history.embedding_dim = 4
    monkeypatch.setattr("harbormaster.history.cli.load_config", lambda _p: config)
    # Replace get_embedding_backend so we don't need fastembed.
    monkeypatch.setattr(
        "harbormaster.history.cli.get_embedding_backend",
        lambda _c: StubVecBackendV1(),
    )

    rc = cli_main(["--dry-run"])
    assert rc == 0

    store2 = _open_v1(tmp_path)
    meta_after = store2.embedding_meta()
    assert meta_after == meta_before
    store2.close()


def test_main_dispatches_reembed_subcommand(monkeypatch):
    """`__main__.main(["reembed", "--help"])` must dispatch to the
    reembed CLI rather than the server parser."""
    from harbormaster import __main__ as m

    captured: list[list[str]] = []

    def fake_reembed_main(argv: list[str]) -> int:
        captured.append(argv)
        return 7

    monkeypatch.setattr("harbormaster.history.cli.main", fake_reembed_main)

    rc = m.main(["reembed", "--dry-run"])
    assert rc == 7
    assert captured == [["--dry-run"]]

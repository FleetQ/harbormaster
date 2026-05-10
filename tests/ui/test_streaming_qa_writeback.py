"""v10.0.0a1: bug fix — Recent Q&A was empty for streamed calls.

The streaming dispatcher (`_emit_chunks_then_result`) used to assemble
the answer from text deltas but never call `_maybe_record_qa`, so
dashboard / fan-out / project-detail Q&A history never populated. This
test pins the new behaviour: after a successful streamed call, the
local sqlite QAStore must contain a row with the assembled answer.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

from harbormaster.config import HarbormasterConfig, HistoryConfig
from harbormaster.history import FTS5Backend, QAStore
from harbormaster.ui.routes import _emit_chunks_then_result


def _config(tmp_path: Path, *, enabled: bool = True, **history_kw: object) -> HarbormasterConfig:
    return HarbormasterConfig(
        history=HistoryConfig(
            enabled=enabled,
            embedding_backend="fts5",
            db_dir=str(tmp_path),
            **history_kw,  # type: ignore[arg-type]
        )
    )


def _open(tmp_path: Path, host: str | None = None) -> QAStore:
    return QAStore.open(
        db_dir=tmp_path,
        host=host,
        embedding_backend=FTS5Backend(),
    )


def _drive_with_ctx(
    iterable: object,
    record_ctx: dict[str, object] | None,
) -> list[dict[str, str]]:
    async def collect() -> list[dict[str, str]]:
        out: list[dict[str, str]] = []
        async for ev in _emit_chunks_then_result(iterable, record_ctx=record_ctx):
            out.append(ev)
        return out

    return asyncio.run(collect())


def test_streamed_call_records_qa_when_enabled(tmp_path: Path) -> None:
    """Phase 1 contract: after a successful streamed call, QAStore
    contains a row with the assembled answer text."""
    config = _config(tmp_path)

    def fake_iter() -> object:
        yield "hello "
        yield "world"

    events = _drive_with_ctx(
        fake_iter(),
        record_ctx={
            "config": config,
            "project_name": "alpha",
            "host": None,
            "prompt": "what is X?",
            "tool": "ask_project",
        },
    )

    # Sanity: stream completed normally.
    assert events[-1]["event"] == "result"

    store = _open(tmp_path)
    try:
        assert store.count() == 1
        row = store._conn.execute(
            "SELECT question, answer, project, host, tool FROM qa_log"
        ).fetchone()
        assert row["question"] == "what is X?"
        assert row["answer"] == "hello world"
        assert row["project"] == "alpha"
        assert row["host"] == "local"
        assert row["tool"] == "ask_project"
    finally:
        store.close()


def test_streamed_call_records_qa_with_remote_host(tmp_path: Path) -> None:
    """For `_stream_remote_tool`, host is passed through and stored
    on the per-host db (matches sync-path semantics)."""
    config = _config(tmp_path)

    def fake_iter() -> object:
        yield "remote answer"

    _drive_with_ctx(
        fake_iter(),
        record_ctx={
            "config": config,
            "project_name": "beta",
            "host": "friday",
            "prompt": "remote q",
            "tool": "delegate_task",
        },
    )

    store = _open(tmp_path, host="friday")
    try:
        assert store.count() == 1
        row = store._conn.execute(
            "SELECT host, tool, answer FROM qa_log"
        ).fetchone()
        assert row["host"] == "friday"
        assert row["tool"] == "delegate_task"
        assert row["answer"] == "remote answer"
    finally:
        store.close()


def test_streamed_call_skips_record_when_history_disabled(tmp_path: Path) -> None:
    """Honors existing `_history_logging_enabled_for` gate."""
    config = _config(tmp_path, enabled=False)

    def fake_iter() -> object:
        yield "x"

    _drive_with_ctx(
        fake_iter(),
        record_ctx={
            "config": config,
            "project_name": "alpha",
            "host": None,
            "prompt": "q",
            "tool": "ask_project",
        },
    )

    # Disabled: no db should be created.
    assert list(tmp_path.iterdir()) == []


def test_streamed_call_no_record_ctx_is_safe(tmp_path: Path) -> None:
    """Backwards-compat: callers that don't pass record_ctx (the
    /mcp/* heartbeat path doesn't) get no writeback and no error."""
    def fake_iter() -> object:
        yield "x"

    events = _drive_with_ctx(fake_iter(), record_ctx=None)
    assert events[-1]["event"] == "result"
    assert list(tmp_path.iterdir()) == []


def test_streamed_call_record_failure_does_not_break_stream(
    tmp_path: Path, monkeypatch
) -> None:
    """If `_maybe_record_qa` blows up, the stream still completes."""
    config = _config(tmp_path)

    def boom(*_args: object, **_kw: object) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr("harbormaster.tools._helpers._maybe_record_qa", boom)

    def fake_iter() -> object:
        yield "hi"

    events = _drive_with_ctx(
        fake_iter(),
        record_ctx={
            "config": config,
            "project_name": "alpha",
            "host": None,
            "prompt": "q",
            "tool": "ask_project",
        },
    )
    # Final event MUST still be the result envelope.
    assert events[-1]["event"] == "result"


def test_streamed_call_skips_record_for_empty_answer(tmp_path: Path) -> None:
    """If no chunks were yielded (empty answer), no row is recorded —
    sync-path skips empty answers via the embedding store; mirror that
    here at the caller level by gating on `assembled`."""
    config = _config(tmp_path)

    def fake_iter() -> object:
        return
        yield  # pragma: no cover — make this a generator

    _drive_with_ctx(
        fake_iter(),
        record_ctx={
            "config": config,
            "project_name": "alpha",
            "host": None,
            "prompt": "q",
            "tool": "ask_project",
        },
    )

    assert list(tmp_path.iterdir()) == []

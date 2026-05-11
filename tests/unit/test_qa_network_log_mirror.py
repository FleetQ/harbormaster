"""v21.0.6: every successful tool call's QA record should also land
in the UI's network_log so the dashboard Activity / Timeline tabs
surface stdio-driven activity, not just HTTP /mcp/{server} calls.

These tests pin the mirror behaviour at the `_maybe_record_qa` call
site so a future refactor can't silently break the unified surface.

Tests use the session-wide `network_log` singleton wired up by
``tests/conftest.py`` (its ``HARBORMASTER_NETWORK_LOG_DB`` redirect
points at a tmp file). The autouse `_reset_network_log` fixture from
conftest truncates ``mcp_calls`` between tests so per-test counts
are deterministic.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from harbormaster.config import (
    HarbormasterConfig,
    HistoryConfig,
)
from harbormaster.tools._helpers import _maybe_record_qa
from harbormaster.ui.network_log import network_log


def _cfg_with_history(tmp_path: Path) -> HarbormasterConfig:
    """Build a config with [history] enabled + FTS5 backend so no
    fastembed download is needed."""
    return HarbormasterConfig(
        history=HistoryConfig(
            enabled=True,
            embedding_backend="fts5",
            db_dir=str(tmp_path / "history"),
        ),
    )


def _rows() -> list[dict[str, object]]:
    """Read mcp_calls rows from the active network_log singleton."""
    cur = network_log._conn.execute(  # noqa: SLF001 — internal API
        "SELECT target, tool, status, question_preview, duration_ms "
        "FROM mcp_calls ORDER BY id",
    )
    return [
        {
            "target": r[0],
            "tool": r[1],
            "status": r[2],
            "question_preview": r[3],
            "duration_ms": r[4],
        }
        for r in cur.fetchall()
    ]


def test_maybe_record_qa_mirrors_to_network_log(tmp_path: Path) -> None:
    """Happy path: a successful QA record produces both a qa_log row
    AND a mcp_calls row."""
    cfg = _cfg_with_history(tmp_path)

    _maybe_record_qa(
        config=cfg,
        project_name="alpha",
        host="local",
        prompt="what does this do?",
        answer="it does things.",
        tool="ask_project",
        duration_ms=123,
    )

    rows = _rows()
    assert len(rows) == 1, f"expected one mcp_calls row, got {rows}"
    row = rows[0]
    assert row["target"] == "alpha"
    assert row["tool"] == "ask_project"
    assert row["status"] == "ok"
    assert row["question_preview"] == "what does this do?"
    assert row["duration_ms"] == 123


def test_maybe_record_qa_question_preview_truncated_to_200_chars(
    tmp_path: Path,
) -> None:
    """network_store enforces a 200-char preview cap. Ensure the mirror
    doesn't trip the cap with a long prompt."""
    cfg = _cfg_with_history(tmp_path)
    long_prompt = "x" * 500

    _maybe_record_qa(
        config=cfg,
        project_name="alpha",
        host="local",
        prompt=long_prompt,
        answer="ok",
        tool="ask_project",
        duration_ms=1,
    )

    rows = _rows()
    assert len(rows) == 1
    assert len(str(rows[0]["question_preview"])) == 200


def test_maybe_record_qa_skipped_when_history_disabled(tmp_path: Path) -> None:
    """[history] off → no qa_log AND no network_log mirror."""
    cfg = HarbormasterConfig(history=HistoryConfig(enabled=False))

    _maybe_record_qa(
        config=cfg,
        project_name="alpha",
        host="local",
        prompt="anything",
        answer="anything",
        tool="ask_project",
        duration_ms=1,
    )

    assert _rows() == []


def test_maybe_record_qa_swallows_network_log_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failure inside network_log.record must NOT propagate — the
    QA record path is best-effort and instrumentation breakage cannot
    break the tool dispatch."""
    cfg = _cfg_with_history(tmp_path)

    def _boom(**kwargs: object) -> None:
        raise RuntimeError("simulated network_log explosion")

    monkeypatch.setattr(network_log, "record", _boom)

    # Must not raise.
    _maybe_record_qa(
        config=cfg,
        project_name="alpha",
        host="local",
        prompt="anything",
        answer="anything",
        tool="ask_project",
        duration_ms=1,
    )

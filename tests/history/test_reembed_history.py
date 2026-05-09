"""Unit tests for v7.0.0a4 rolling reembed run-history log.

Covers:
  * read_runs returns [] when missing
  * read_runs handles corrupt JSON without raising
  * append_run round-trips a single record
  * append_run prunes to MAX_HISTORY_RECORDS (rolling)
  * append_run swallows disk failures (read-only parent)
  * file is created with mode 0600
  * record_from_state_and_errors composes counts correctly
  * GET /api/history/reembed/runs serves the log
  * runner integration: run_auto_reembed appends a record on completion
"""
from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from harbormaster.config import HarbormasterConfig, HistoryConfig
from harbormaster.history.reembed_history import (
    MAX_HISTORY_RECORDS,
    ReembedRunRecord,
    _resolve_history_path,
    append_run,
    read_runs,
    record_from_state_and_errors,
)
from harbormaster.ui.app import create_app

# --- read_runs ---------------------------------------------------------


def test_read_runs_returns_empty_list_when_missing(tmp_path: Path) -> None:
    assert read_runs(tmp_path / "missing.json") == []


def test_read_runs_handles_corrupt_json(tmp_path: Path) -> None:
    p = tmp_path / "history.json"
    p.write_text("not valid json {{")
    assert read_runs(p) == []


def test_read_runs_drops_individual_bad_rows_keeps_good(
    tmp_path: Path,
) -> None:
    p = tmp_path / "history.json"
    p.write_text(
        json.dumps(
            [
                {"started_at": 1.0, "finished_at": 2.0, "total": 1},
                {"this is not": "a valid record"},
                {"started_at": 3.0, "finished_at": 4.0, "total": 2},
            ]
        )
    )
    runs = read_runs(p)
    assert len(runs) == 2
    assert runs[0].total == 1
    assert runs[1].total == 2


# --- append_run --------------------------------------------------------


def _make_record(t: float = 100.0) -> ReembedRunRecord:
    return ReembedRunRecord(
        started_at=t,
        finished_at=t + 10.0,
        total=2,
        succeeded=2,
        failed=0,
        cancelled=0,
        model="fts5",
    )


def test_append_run_creates_file_with_one_record(tmp_path: Path) -> None:
    p = tmp_path / "history.json"
    append_run(_make_record(), p)
    runs = read_runs(p)
    assert len(runs) == 1
    assert runs[0].total == 2


def test_append_run_appends_in_order(tmp_path: Path) -> None:
    p = tmp_path / "history.json"
    append_run(_make_record(100.0), p)
    append_run(_make_record(200.0), p)
    append_run(_make_record(300.0), p)
    runs = read_runs(p)
    assert [r.started_at for r in runs] == [100.0, 200.0, 300.0]


def test_append_run_prunes_to_max(tmp_path: Path) -> None:
    p = tmp_path / "history.json"
    for i in range(MAX_HISTORY_RECORDS + 10):
        append_run(_make_record(float(i)), p)
    runs = read_runs(p)
    assert len(runs) == MAX_HISTORY_RECORDS
    # Oldest dropped — first surviving record's started_at should be 10.
    assert runs[0].started_at == 10.0
    assert runs[-1].started_at == float(MAX_HISTORY_RECORDS + 10 - 1)


def test_append_run_swallows_disk_failure(tmp_path: Path) -> None:
    bad = tmp_path / "ro" / "history.json"
    bad.parent.mkdir()
    bad.parent.chmod(0o500)
    try:
        # Must not raise.
        append_run(_make_record(), bad)
    finally:
        bad.parent.chmod(0o700)


def test_append_run_writes_mode_0600(tmp_path: Path) -> None:
    p = tmp_path / "history.json"
    append_run(_make_record(), p)
    mode = stat.S_IMODE(os.stat(p).st_mode)
    assert mode == 0o600, f"expected 0600, got {oct(mode)}"


# --- record_from_state_and_errors --------------------------------------


def test_record_counts_succeeded_failed_zero_cancelled() -> None:
    r = record_from_state_and_errors(
        started_at=1.0,
        finished_at=2.0,
        total=4,
        processed=4,
        errors=[],
        cancelled=False,
        model="fts5",
    )
    assert r.succeeded == 4
    assert r.failed == 0
    assert r.cancelled == 0


def test_record_counts_failures() -> None:
    r = record_from_state_and_errors(
        started_at=1.0,
        finished_at=2.0,
        total=4,
        processed=4,
        errors=["host1: boom", "host2: kaboom"],
        cancelled=False,
        model=None,
    )
    assert r.succeeded == 2
    assert r.failed == 2
    assert r.cancelled == 0


def test_record_counts_cancelled_remainder() -> None:
    r = record_from_state_and_errors(
        started_at=1.0,
        finished_at=2.0,
        total=5,
        processed=2,
        errors=[],
        cancelled=True,
        model="fts5",
    )
    assert r.succeeded == 2
    assert r.failed == 0
    assert r.cancelled == 3  # 5 - 2 unprocessed


# --- HTTP route --------------------------------------------------------


def test_api_runs_returns_empty_when_no_history(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(
        "HARBORMASTER_REEMBED_HISTORY_FILE", str(tmp_path / "history.json")
    )
    cfg = HarbormasterConfig(
        history=HistoryConfig(enabled=True, embedding_backend="fts5"),
    )
    client = TestClient(create_app(cfg))
    r = client.get("/api/history/reembed/runs")
    assert r.status_code == 200
    assert r.json() == {"runs": []}


def test_api_runs_returns_appended_records(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    p = tmp_path / "history.json"
    monkeypatch.setenv("HARBORMASTER_REEMBED_HISTORY_FILE", str(p))
    append_run(_make_record(100.0), p)
    append_run(_make_record(200.0), p)

    cfg = HarbormasterConfig(
        history=HistoryConfig(enabled=True, embedding_backend="fts5"),
    )
    client = TestClient(create_app(cfg))
    r = client.get("/api/history/reembed/runs")
    assert r.status_code == 200
    body = r.json()
    assert len(body["runs"]) == 2
    assert body["runs"][0]["started_at"] == 100.0


# --- env override ------------------------------------------------------


def test_env_override_resolves_history_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "custom.json"
    monkeypatch.setenv("HARBORMASTER_REEMBED_HISTORY_FILE", str(target))
    assert _resolve_history_path() == target


# --- runner integration ------------------------------------------------


def test_runner_appends_history_record_on_completion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """run_auto_reembed must append exactly one record per run."""
    monkeypatch.setattr(
        "harbormaster.history.auto_reembed._RETRY_BACKOFF_SECONDS",
        (0.0, 0.0, 0.0),
    )
    history_path = tmp_path / "history.json"
    monkeypatch.setenv("HARBORMASTER_REEMBED_HISTORY_FILE", str(history_path))

    from harbormaster.history import QAStore
    from harbormaster.history.auto_reembed import run_auto_reembed

    class _NoDrift:
        def has_embedding_drift(self) -> bool:
            return False

        def reembed(
            self, *, batch_size: int = 100, resume: bool = True
        ) -> tuple[int, int]:
            return 0, 0

        def close(self) -> None:
            pass

    def open_stub(*, db_dir: str, host: str | None,
                  embedding_backend: Any, embedding_dim: int) -> Any:
        return _NoDrift()

    monkeypatch.setattr(QAStore, "open", open_stub)

    cfg = HarbormasterConfig(
        history=HistoryConfig(
            enabled=True,
            embedding_backend="fts5",
            db_dir=str(tmp_path / "db"),
        ),
    )
    state_path = tmp_path / "state.json"
    run_auto_reembed(cfg, state_path=state_path)

    runs = read_runs(history_path)
    assert len(runs) == 1
    assert runs[0].total == 1  # only "local" target
    assert runs[0].succeeded == 1
    assert runs[0].failed == 0
    assert runs[0].cancelled == 0
    assert runs[0].finished_at >= runs[0].started_at


# --- UI template assertion --------------------------------------------


def test_dashboard_template_renders_runs_table_block() -> None:
    cfg = HarbormasterConfig(
        history=HistoryConfig(enabled=True, embedding_backend="fts5"),
    )
    client = TestClient(create_app(cfg))
    r = client.get("/")
    assert r.status_code == 200
    assert "loadRuns()" in r.text
    assert "recent runs" in r.text
    # Table headers present.
    assert ">finished<" in r.text
    assert ">duration<" in r.text

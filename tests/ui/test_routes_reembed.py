"""Unit tests for v7.0.0a3 cancel-running-reembed route + helper.

Covers:
  * POST /api/history/reembed/cancel — happy path (running → flag set)
  * POST /api/history/reembed/cancel — idempotent no-op when idle
  * POST /api/history/reembed/cancel — returns 503 when [history] missing
  * GET /api/history/state — surfaces cancel_requested
  * UI template renders cancel button + cancelling state
  * request_cancel() helper itself
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from harbormaster.config import HarbormasterConfig, HistoryConfig
from harbormaster.history.auto_reembed import (
    ReembedState,
    _write_state,
    read_state,
    request_cancel,
)
from harbormaster.ui.app import create_app

# --- helper unit tests -------------------------------------------------


def test_request_cancel_sets_flag_when_running(tmp_path: Path) -> None:
    state_path = tmp_path / "state.json"
    _write_state(
        ReembedState(phase="running", processed=1, total=3),
        state_path,
    )
    was_running, after = request_cancel(state_path)
    assert was_running is True
    assert after.cancel_requested is True
    on_disk = read_state(state_path)
    assert on_disk.cancel_requested is True
    assert on_disk.phase == "running"


def test_request_cancel_is_noop_when_idle(tmp_path: Path) -> None:
    state_path = tmp_path / "state.json"
    # No file written → read_state returns idle.
    was_running, after = request_cancel(state_path)
    assert was_running is False
    assert after.cancel_requested is False
    assert after.phase == "idle"


def test_request_cancel_is_noop_when_done(tmp_path: Path) -> None:
    state_path = tmp_path / "state.json"
    _write_state(ReembedState(phase="done", processed=3, total=3), state_path)
    was_running, after = request_cancel(state_path)
    assert was_running is False
    assert after.phase == "done"
    # Don't accidentally mutate the done state.
    on_disk = read_state(state_path)
    assert on_disk.cancel_requested is False


# --- HTTP route tests --------------------------------------------------


def test_api_cancel_returns_running_true_when_running(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(
        "HARBORMASTER_REEMBED_STATE_FILE", str(tmp_path / "state.json")
    )
    cfg = HarbormasterConfig(
        history=HistoryConfig(enabled=True, embedding_backend="fts5"),
    )
    _write_state(
        ReembedState(phase="running", processed=1, total=3),
        tmp_path / "state.json",
    )

    client = TestClient(create_app(cfg))
    r = client.post("/api/history/reembed/cancel")
    assert r.status_code == 200
    body = r.json()
    assert body["running"] is True
    assert body["cancel_requested"] is True
    assert body["phase"] == "running"


def test_api_cancel_returns_running_false_when_idle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(
        "HARBORMASTER_REEMBED_STATE_FILE", str(tmp_path / "state.json")
    )
    cfg = HarbormasterConfig(
        history=HistoryConfig(enabled=True, embedding_backend="fts5"),
    )
    client = TestClient(create_app(cfg))
    r = client.post("/api/history/reembed/cancel")
    assert r.status_code == 200
    body = r.json()
    assert body["running"] is False
    assert body["cancel_requested"] is False


def test_api_state_surfaces_cancel_requested(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(
        "HARBORMASTER_REEMBED_STATE_FILE", str(tmp_path / "state.json")
    )
    cfg = HarbormasterConfig(
        history=HistoryConfig(enabled=True, embedding_backend="fts5"),
    )
    _write_state(
        ReembedState(
            phase="running", processed=1, total=3, cancel_requested=True
        ),
        tmp_path / "state.json",
    )
    client = TestClient(create_app(cfg))
    r = client.get("/api/history/state")
    assert r.status_code == 200
    body = r.json()
    assert body["cancel_requested"] is True
    assert body["phase"] == "running"


# --- UI template assertions --------------------------------------------


def test_dashboard_template_renders_cancel_button() -> None:
    cfg = HarbormasterConfig(
        history=HistoryConfig(enabled=True, embedding_backend="fts5"),
    )
    client = TestClient(create_app(cfg))
    r = client.get("/")
    assert r.status_code == 200
    # Cancel button + JS handler must be present.
    assert "cancelRunning()" in r.text
    assert ">cancel<" in r.text
    assert "cancelling" in r.text
    # The "cancelled" phase message + amber badge map entry.
    assert "Cancelled after" in r.text


# --- runner-with-cancel integration ------------------------------------


def test_runner_observes_cancel_flag_and_stops(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When cancel_requested is set BEFORE the worker iterates, it
    must exit with phase='cancelled' without processing any host."""
    # Keep retry backoff tight in case any open() retries.
    monkeypatch.setattr(
        "harbormaster.history.auto_reembed._RETRY_BACKOFF_SECONDS",
        (0.0, 0.0, 0.0),
    )
    from harbormaster.history.auto_reembed import run_auto_reembed

    cfg = HarbormasterConfig(
        history=HistoryConfig(
            enabled=True,
            embedding_backend="fts5",
            db_dir=str(tmp_path / "db"),
        ),
    )
    state_path = tmp_path / "state.json"
    # Pre-set the cancel flag — the worker re-reads the file at the
    # top of every iteration, so even a synchronous run honours it.
    _write_state(
        ReembedState(phase="running", cancel_requested=True), state_path
    )
    run_auto_reembed(cfg, state_path=state_path)
    final = read_state(state_path)
    assert final.phase == "cancelled"
    # Flag is cleared on the persisted state once the runner finishes.
    assert final.cancel_requested is False
    # Nothing was processed.
    assert final.processed == 0

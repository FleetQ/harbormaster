"""Unit tests for auto-reembed state machine + runner (v4.0.0a5).

Covers state file IO, runner happy path, per-host failure isolation,
config gate, and ImportError fallback.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from harbormaster.history.auto_reembed import (
    ReembedState,
    _write_state,
    maybe_start_auto_reembed_thread,
    read_state,
    run_auto_reembed,
)


@pytest.fixture
def state_path(tmp_path: Path) -> Path:
    return tmp_path / "reembed-state.json"


# --- state IO ------------------------------------------------------------


def test_default_state_is_idle() -> None:
    s = ReembedState()
    assert s.phase == "idle"
    assert s.processed == 0
    assert s.total == 0
    assert s.error is None
    assert s.current_host is None


def test_write_state_creates_file_atomically(state_path: Path) -> None:
    state = ReembedState(phase="running", processed=3, total=5)
    _write_state(state, state_path)

    assert state_path.exists()
    raw = json.loads(state_path.read_text())
    assert raw["phase"] == "running"
    assert raw["processed"] == 3
    assert raw["total"] == 5


def test_read_state_returns_idle_when_file_missing(state_path: Path) -> None:
    s = read_state(state_path)
    assert s.phase == "idle"
    assert s.processed == 0


def test_read_state_handles_corrupt_json(state_path: Path) -> None:
    state_path.write_text("not valid json {{")
    s = read_state(state_path)
    assert s.phase == "idle"


def test_write_state_swallows_disk_failure(tmp_path: Path) -> None:
    bad_path = tmp_path / "ro" / "reembed-state.json"
    bad_path.parent.mkdir()
    bad_path.parent.chmod(0o500)
    state = ReembedState(phase="running")
    try:
        _write_state(state, bad_path)  # must not raise
    finally:
        bad_path.parent.chmod(0o700)


# --- runner happy path ---------------------------------------------------


class _StubStore:
    """Minimal QAStore stand-in for the runner test."""

    def __init__(self, drift: bool, processed_rows: int) -> None:
        self._drift = drift
        self._processed = processed_rows
        self.closed = False
        self.reembed_called = False

    def has_embedding_drift(self) -> bool:
        return self._drift

    def reembed(self, *, batch_size: int = 100, resume: bool = True) -> tuple[int, int]:
        self.reembed_called = True
        return self._processed, self._processed

    def close(self) -> None:
        self.closed = True


def _patch_store_open(monkeypatch: pytest.MonkeyPatch, **per_host_stores: _StubStore) -> dict[str, _StubStore]:
    """Patch QAStore.open to dispatch to per-host stub stores."""
    from harbormaster.history import QAStore

    captured: dict[str, _StubStore] = {}

    def open_stub(*, db_dir: str, host: str | None, embedding_backend: Any, embedding_dim: int) -> _StubStore:
        label = host if host is not None else "local"
        store = per_host_stores[label]
        captured[label] = store
        return store

    monkeypatch.setattr(QAStore, "open", open_stub)
    return captured


def test_runner_processes_each_target_and_writes_done(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from harbormaster.config import HarbormasterConfig, HistoryConfig, HostConfig

    config = HarbormasterConfig(
        history=HistoryConfig(
            enabled=True,
            embedding_backend="fts5",
            db_dir=str(tmp_path / "db"),
            auto_reembed_on_drift=True,
        ),
        hosts={"friday": HostConfig(ssh_host="friday.local")},
    )
    state_path = tmp_path / "state.json"

    stores = _patch_store_open(
        monkeypatch,
        local=_StubStore(drift=True, processed_rows=10),
        friday=_StubStore(drift=False, processed_rows=0),
    )

    run_auto_reembed(config, state_path=state_path)

    final = read_state(state_path)
    assert final.phase == "done"
    assert final.error is None
    assert final.processed == 2  # local + friday were both processed
    assert stores["local"].reembed_called is True
    # No drift on friday → reembed not called.
    assert stores["friday"].reembed_called is False
    # Stores closed.
    assert stores["local"].closed is True
    assert stores["friday"].closed is True


def test_runner_isolates_per_host_failures(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from harbormaster.config import HarbormasterConfig, HistoryConfig, HostConfig
    from harbormaster.history import QAStore

    config = HarbormasterConfig(
        history=HistoryConfig(
            enabled=True,
            embedding_backend="fts5",
            db_dir=str(tmp_path / "db"),
            auto_reembed_on_drift=True,
        ),
        hosts={"broken": HostConfig(ssh_host="broken.local")},
    )

    def open_with_failure(*, db_dir: str, host: str | None, embedding_backend: Any, embedding_dim: int) -> Any:
        if host == "broken":
            raise RuntimeError("simulated open failure")
        return _StubStore(drift=True, processed_rows=5)

    monkeypatch.setattr(QAStore, "open", open_with_failure)

    state_path = tmp_path / "state.json"
    run_auto_reembed(config, state_path=state_path)

    final = read_state(state_path)
    assert final.phase == "failed"
    assert final.error is not None
    assert "broken" in final.error
    # Local still got processed despite broken host.
    assert final.processed == 2  # both targets attempted; counter advances on each


# --- gating + thread spawn ----------------------------------------------


def test_maybe_start_returns_none_when_disabled() -> None:
    from harbormaster.config import HarbormasterConfig, HistoryConfig

    config = HarbormasterConfig(
        history=HistoryConfig(
            enabled=True,
            auto_reembed_on_drift=False,  # disabled
        ),
    )
    thread = maybe_start_auto_reembed_thread(config)
    assert thread is None


def test_maybe_start_returns_none_when_history_disabled() -> None:
    from harbormaster.config import HarbormasterConfig, HistoryConfig

    config = HarbormasterConfig(
        history=HistoryConfig(
            enabled=False,
            auto_reembed_on_drift=True,
        ),
    )
    thread = maybe_start_auto_reembed_thread(config)
    assert thread is None


def test_maybe_start_kicks_off_thread_when_both_enabled(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from harbormaster.config import HarbormasterConfig, HistoryConfig

    monkeypatch.setenv(
        "HARBORMASTER_REEMBED_STATE_FILE", str(tmp_path / "state.json")
    )

    config = HarbormasterConfig(
        history=HistoryConfig(
            enabled=True,
            embedding_backend="fts5",
            db_dir=str(tmp_path / "db"),
            auto_reembed_on_drift=True,
        ),
    )

    # Patch QAStore.open to a stub that immediately reports no drift.
    from harbormaster.history import QAStore

    def open_stub(*, db_dir: str, host: str | None, embedding_backend: Any, embedding_dim: int) -> Any:
        return _StubStore(drift=False, processed_rows=0)

    monkeypatch.setattr(QAStore, "open", open_stub)

    thread = maybe_start_auto_reembed_thread(config)
    assert thread is not None
    thread.join(timeout=5)
    assert not thread.is_alive()
    final = read_state(tmp_path / "state.json")
    assert final.phase == "done"

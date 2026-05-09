"""Unit tests for BridgeStateWriter / read_bridge_state (v3.0.0a2).

Cross-process state file: writer in MCP process, reader in UI process.
Tests use a tempdir so they never touch the real ~/.harbormaster dir.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

from harbormaster.fleetq.state import (
    BridgeRuntimeState,
    BridgeStateWriter,
    read_bridge_state,
)


@pytest.fixture
def state_path(tmp_path: Path) -> Path:
    return tmp_path / "bridge-state.json"


def test_writer_creates_file_on_first_update(state_path: Path) -> None:
    writer = BridgeStateWriter(state_path)

    writer.update(connected=True, team_id="team-1", session_id="sess-1")

    assert state_path.exists()
    raw = json.loads(state_path.read_text())
    assert raw["connected"] is True
    assert raw["team_id"] == "team-1"
    assert raw["session_id"] == "sess-1"
    assert raw["writer_pid"] == os.getpid()
    assert raw["last_heartbeat"] is not None  # auto-stamped on connected=True


def test_writer_creates_parent_directory(tmp_path: Path) -> None:
    nested = tmp_path / "deep" / "nested" / "bridge-state.json"
    writer = BridgeStateWriter(nested)
    writer.update(connected=True)
    assert nested.exists()


def test_writer_partial_update_preserves_prior_fields(state_path: Path) -> None:
    writer = BridgeStateWriter(state_path)
    writer.update(connected=True, team_id="team-1", session_id="sess-1")

    writer.update(subscribed=True)

    raw = json.loads(state_path.read_text())
    assert raw["team_id"] == "team-1"
    assert raw["session_id"] == "sess-1"
    assert raw["subscribed"] is True
    assert raw["connected"] is True


def test_writer_explicit_last_heartbeat_overrides_auto_stamp(state_path: Path) -> None:
    writer = BridgeStateWriter(state_path)

    writer.update(connected=True, last_heartbeat=12345.0)

    raw = json.loads(state_path.read_text())
    assert raw["last_heartbeat"] == 12345.0


def test_writer_mark_disconnected_clears_subscribed(state_path: Path) -> None:
    writer = BridgeStateWriter(state_path)
    writer.update(connected=True, subscribed=True)

    writer.mark_disconnected(error="boom")

    raw = json.loads(state_path.read_text())
    assert raw["connected"] is False
    assert raw["subscribed"] is False
    assert raw["last_error"] == "boom"


def test_writer_swallows_disk_failure(tmp_path: Path) -> None:
    """Writer must never crash the heartbeat thread — disk full / readonly
    parent should log+continue."""
    bad_path = tmp_path / "readonly" / "bridge-state.json"
    bad_path.parent.mkdir()
    bad_path.parent.chmod(0o500)  # read+execute only

    writer = BridgeStateWriter(bad_path)
    try:
        writer.update(connected=True)  # must not raise
    finally:
        bad_path.parent.chmod(0o700)


def test_reader_returns_empty_view_when_file_missing(state_path: Path) -> None:
    view = read_bridge_state(state_path)

    assert view.state_file_present is False
    assert view.state.connected is False
    assert view.age_seconds is None
    assert view.stale is False  # never-written ≠ stale


def test_reader_marks_stale_when_heartbeat_old(state_path: Path) -> None:
    writer = BridgeStateWriter(state_path)
    # Manually pin last_heartbeat to a time in the past.
    writer.update(connected=True, last_heartbeat=time.time() - 120)

    view = read_bridge_state(state_path, freshness_seconds=30)

    assert view.stale is True
    assert view.age_seconds is not None
    assert view.age_seconds > 30


def test_reader_fresh_when_heartbeat_recent(state_path: Path) -> None:
    writer = BridgeStateWriter(state_path)
    writer.update(connected=True)  # auto-stamps current time

    view = read_bridge_state(state_path, freshness_seconds=30)

    assert view.stale is False
    assert view.age_seconds is not None
    assert view.age_seconds < 5


def test_reader_handles_corrupt_json(state_path: Path) -> None:
    state_path.write_text("not valid json {{")

    view = read_bridge_state(state_path)

    assert view.state_file_present is True
    assert view.stale is True
    assert view.state.connected is False


def test_reader_handles_partial_state(state_path: Path) -> None:
    """A future field added by a newer writer must not break older readers."""
    state_path.write_text(json.dumps({"connected": True, "future_field": "ignored"}))

    view = read_bridge_state(state_path)

    assert view.state.connected is True


def test_resolve_state_path_honours_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    custom = tmp_path / "custom-bridge.json"
    monkeypatch.setenv("HARBORMASTER_BRIDGE_STATE_FILE", str(custom))

    writer = BridgeStateWriter()
    writer.update(connected=True)

    assert custom.exists()


def test_round_trip_writer_reader(state_path: Path) -> None:
    writer = BridgeStateWriter(state_path)
    writer.update(
        connected=True,
        subscribed=True,
        team_id="team-1",
        session_id="sess-1",
    )

    view = read_bridge_state(state_path)

    assert view.state.connected is True
    assert view.state.subscribed is True
    assert view.state.team_id == "team-1"
    assert view.state.session_id == "sess-1"
    assert view.state_file_present is True


def test_runtime_state_default_construct() -> None:
    s = BridgeRuntimeState()
    assert s.connected is False
    assert s.subscribed is False
    assert s.team_id is None
    assert s.last_heartbeat is None
    assert s.last_error is None
    assert s.writer_pid is None

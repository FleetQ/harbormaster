"""Unit tests for `harbormaster-mcp dispatcher status` CLI (v6.0.0a6)."""
from __future__ import annotations

from pathlib import Path

import pytest

from harbormaster.dispatcher_cli import main
from harbormaster.fleetq.dispatcher import SAFE_FOR_PARALLEL


@pytest.fixture
def empty_config(tmp_path: Path) -> Path:
    """A minimal config with default dispatcher settings."""
    cfg = tmp_path / "harbormaster.toml"
    # Must be a valid TOML file with no fleetq overrides — defaults apply.
    cfg.write_text("[server]\n")
    return cfg


@pytest.fixture
def pool_config(tmp_path: Path) -> Path:
    """Config that opts into the pool with a deny list."""
    cfg = tmp_path / "harbormaster.toml"
    cfg.write_text(
        "[fleetq]\n"
        'dispatcher_max_workers = 4\n'
        'dispatcher_unsafe_tools = ["delegate_task", "third_party_plugin"]\n'
    )
    return cfg


def test_dispatcher_status_default_single_worker(
    empty_config: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = main(["status", "--config", str(empty_config)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "dispatcher_max_workers: 1" in out
    assert "single-worker" in out  # informational hint
    # All SAFE_FOR_PARALLEL tools listed.
    for tool in SAFE_FOR_PARALLEL:
        assert tool in out
    # No deny list.
    assert "deny list: (empty)" in out


def test_dispatcher_status_with_pool_and_deny_list(
    pool_config: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = main(["status", "--config", str(pool_config)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "dispatcher_max_workers: 4" in out
    # Pool is on, so the "single-worker" hint must NOT appear.
    assert "single-worker" not in out
    # Deny list rendered with annotations.
    assert "delegate_task" in out
    assert "(in allowlist)" in out  # delegate_task is in SAFE_FOR_PARALLEL
    assert "third_party_plugin" in out
    assert "(unknown tool)" in out  # third_party_plugin isn't


def test_dispatcher_status_effective_set_excludes_deny_list(
    pool_config: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = main(["status", "--config", str(pool_config)])
    assert rc == 0
    out = capsys.readouterr().out
    # Find the "Effective parallel set" section and check delegate_task
    # is not in it (it's deny-listed).
    effective_marker = "Effective parallel set"
    idx = out.find(effective_marker)
    assert idx != -1
    effective_section = out[idx:]
    assert "delegate_task" not in effective_section
    # But ask_project (not deny-listed) IS in it.
    assert "ask_project" in effective_section


def test_dispatcher_status_unknown_action_exits_nonzero(
    empty_config: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit):
        main(["unknown_action"])


def test_dispatcher_status_missing_config_path_handled_gracefully(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Non-existent config file path does NOT crash the CLI; defaults
    apply (load_config tolerates missing files)."""
    nonexistent = tmp_path / "missing.toml"
    rc = main(["status", "--config", str(nonexistent)])
    # Either succeeds with defaults or fails cleanly with rc=1.
    # Both are acceptable; the key is no traceback.
    assert rc in (0, 1)

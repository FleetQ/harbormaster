"""Unit tests for `harbormaster-mcp config check` CLI (v14.0.0a2)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from harbormaster.config_cli import main


@pytest.fixture
def minimal_config(tmp_path: Path) -> Path:
    cfg = tmp_path / "harbormaster.toml"
    cfg.write_text("[server]\n")
    return cfg


@pytest.fixture
def fleetq_enabled_no_token(tmp_path: Path) -> Path:
    cfg = tmp_path / "harbormaster.toml"
    cfg.write_text(
        "[fleetq]\n"
        "enabled = true\n"
        'base_url = "https://fleetq.example.com"\n'
    )
    return cfg


@pytest.fixture
def fleetq_enabled_no_url(tmp_path: Path) -> Path:
    cfg = tmp_path / "harbormaster.toml"
    cfg.write_text(
        "[fleetq]\n"
        "enabled = true\n"
        'base_url = ""\n'
    )
    return cfg


@pytest.fixture
def bad_default_backend(tmp_path: Path) -> Path:
    cfg = tmp_path / "harbormaster.toml"
    cfg.write_text(
        'default_backend = "missing"\n'
    )
    return cfg


def test_check_minimal_config_exits_zero(
    minimal_config: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Bare minimum config with no extras = exit 0 plus an INFO no_hosts."""
    rc = main(["check", "--config", str(minimal_config)])
    # no_hosts is INFO-only — exit 0.
    assert rc == 0
    out = capsys.readouterr().out
    assert "no_hosts" in out
    assert "INFO" in out


def test_check_fleetq_enabled_without_token_warns(
    fleetq_enabled_no_token: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("FLEETQ_API_TOKEN", raising=False)
    rc = main(["check", "--config", str(fleetq_enabled_no_token)])
    assert rc == 1, "missing token = WARN = exit 1"
    out = capsys.readouterr().out
    assert "fleetq_token_env_unset" in out
    assert "WARN" in out


def test_check_fleetq_enabled_without_url_errors(
    fleetq_enabled_no_url: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = main(["check", "--config", str(fleetq_enabled_no_url)])
    assert rc == 2, "missing base_url = ERROR = exit 2"
    out = capsys.readouterr().out
    assert "fleetq_base_url_missing" in out
    assert "ERROR" in out


def test_check_bad_default_backend_errors(
    bad_default_backend: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = main(["check", "--config", str(bad_default_backend)])
    assert rc == 2
    out = capsys.readouterr().out
    assert "default_backend_missing" in out


def test_check_json_output_shape(
    fleetq_enabled_no_url: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = main(["check", "--config", str(fleetq_enabled_no_url), "--json"])
    assert rc == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert payload["severity"] == "ERROR"
    codes = {f["code"] for f in payload["findings"]}
    assert "fleetq_base_url_missing" in codes
    # Every finding has the required keys.
    for f in payload["findings"]:
        assert set(f.keys()) >= {"severity", "code", "message"}


def test_check_load_failure_emits_error_finding(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Pointing at a non-existent config = exit 2 + config_load_failed."""
    missing = tmp_path / "does_not_exist.toml"
    rc = main(["check", "--config", str(missing), "--json"])
    assert rc == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["severity"] == "ERROR"
    assert payload["findings"][0]["code"] == "config_load_failed"


def test_check_unknown_action_exits_two(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["nonsense"])
    # argparse rejects with exit 2 (its standard "invalid arguments" code).
    assert exc.value.code == 2

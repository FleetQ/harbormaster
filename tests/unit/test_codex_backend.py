"""Tests for harbormaster.backends.codex.CodexBackend (v2.0.0a3)."""
from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from harbormaster.backends import (
    CodexBackend,
    get_backend,
    get_backend_for_project,
)
from harbormaster.backends.base import BackendError, BackendResult
from harbormaster.config import BackendConfig, HarbormasterConfig


@pytest.fixture
def cfg() -> BackendConfig:
    return BackendConfig(binary="codex", extra_args=["exec"])


@pytest.fixture
def backend(cfg: BackendConfig) -> CodexBackend:
    return CodexBackend(cfg)


# --- ask_local ----------------------------------------------------------


def _make_completed(rc: int, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=[], returncode=rc, stdout=stdout, stderr=stderr)


def test_ask_local_returns_stdout_as_output(backend: CodexBackend, tmp_path: Path):
    with patch("harbormaster.backends.codex.subprocess.run") as run:
        run.return_value = _make_completed(0, "Hello, world!\n")
        result = backend.ask_local(cwd=tmp_path, prompt="hi", max_turns=3)
    assert isinstance(result, BackendResult)
    assert result.output == "Hello, world!"
    assert result.duration_ms >= 0


def test_ask_local_includes_extra_args_in_command(backend: CodexBackend, tmp_path: Path):
    with patch("harbormaster.backends.codex.subprocess.run") as run:
        run.return_value = _make_completed(0, "ok")
        backend.ask_local(cwd=tmp_path, prompt="prompt-text", max_turns=1)
    cmd = run.call_args.args[0]
    # [binary, *extra_args, prompt]
    assert cmd[0] == "codex"
    assert "exec" in cmd
    assert cmd[-1] == "prompt-text"


def test_ask_local_raises_on_timeout(backend: CodexBackend, tmp_path: Path):
    with patch("harbormaster.backends.codex.subprocess.run") as run:
        run.side_effect = subprocess.TimeoutExpired(cmd=["codex"], timeout=10)
        with pytest.raises(BackendError) as exc:
            backend.ask_local(cwd=tmp_path, prompt="hi", max_turns=1)
    assert exc.value.code == "timeout"


def test_ask_local_raises_on_nonzero_exit(backend: CodexBackend, tmp_path: Path):
    with patch("harbormaster.backends.codex.subprocess.run") as run:
        run.return_value = _make_completed(2, "", "fatal: something broke")
        with pytest.raises(BackendError) as exc:
            backend.ask_local(cwd=tmp_path, prompt="hi", max_turns=1)
    assert exc.value.code == "exit_nonzero"
    assert "fatal" in str(exc.value)


def test_ask_local_raises_on_missing_binary(tmp_path: Path):
    cfg = BackendConfig(binary="this-binary-does-not-exist-xyz")
    b = CodexBackend(cfg)
    with patch("harbormaster.backends.codex.subprocess.run") as run:
        run.side_effect = FileNotFoundError("not found")
        with pytest.raises(BackendError) as exc:
            b.ask_local(cwd=tmp_path, prompt="hi", max_turns=1)
    assert exc.value.code == "exit_nonzero"
    assert "not found" in str(exc.value).lower() or "this-binary" in str(exc.value)


def test_ask_local_raises_on_empty_stdout(backend: CodexBackend, tmp_path: Path):
    with patch("harbormaster.backends.codex.subprocess.run") as run:
        run.return_value = _make_completed(0, "   \n  \n")
        with pytest.raises(BackendError) as exc:
            backend.ask_local(cwd=tmp_path, prompt="hi", max_turns=1)
    assert exc.value.code == "parse_failure"


# --- ask_remote ---------------------------------------------------------


def _ssh_completed(rc: int, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=[], returncode=rc, stdout=stdout, stderr=stderr)


def test_ask_remote_passes_through_stdout(backend: CodexBackend):
    with patch("harbormaster.backends.codex.run_ssh") as ssh:
        ssh.return_value = _ssh_completed(0, "remote answer\n")
        result = backend.ask_remote(
            host="myhost",
            remote_cwd="/srv/app",
            prompt="hi",
            max_turns=1,
            connect_timeout=5,
            total_timeout=30,
        )
    assert result.output == "remote answer"


def test_ask_remote_quotes_user_supplied_values(backend: CodexBackend):
    with patch("harbormaster.backends.codex.run_ssh") as ssh:
        ssh.return_value = _ssh_completed(0, "ok")
        backend.ask_remote(
            host="myhost",
            remote_cwd="/srv/app with spaces",
            prompt="hello'world",
            max_turns=1,
            connect_timeout=5,
            total_timeout=30,
        )
    cmd = ssh.call_args.args[1]
    # remote_cwd is quoted
    assert "'/srv/app with spaces'" in cmd
    # prompt is quoted (single-quote escape via shlex)
    assert "hello" in cmd
    # binary + extra_args
    assert "codex" in cmd
    assert "exec" in cmd


def test_ask_remote_maps_ssh_failure_to_ssh_error_code(backend: CodexBackend):
    with patch("harbormaster.backends.codex.run_ssh") as ssh, patch(
        "harbormaster.backends.codex.diagnose_ssh_failure"
    ) as diag:
        ssh.return_value = _ssh_completed(255, "", "Connection refused")
        diag.return_value = "ssh to 'myhost' refused (rc=255)"
        with pytest.raises(BackendError) as exc:
            backend.ask_remote(
                host="myhost",
                remote_cwd="/x",
                prompt="hi",
                max_turns=1,
                connect_timeout=5,
                total_timeout=30,
            )
    assert exc.value.code == "ssh_error"


def test_ask_remote_maps_remote_nonzero_exit(backend: CodexBackend):
    with patch("harbormaster.backends.codex.run_ssh") as ssh, patch(
        "harbormaster.backends.codex.diagnose_ssh_failure"
    ) as diag:
        ssh.return_value = _ssh_completed(7, "", "remote codex blew up")
        diag.return_value = None
        with pytest.raises(BackendError) as exc:
            backend.ask_remote(
                host="myhost",
                remote_cwd="/x",
                prompt="hi",
                max_turns=1,
                connect_timeout=5,
                total_timeout=30,
            )
    assert exc.value.code == "exit_nonzero"


# --- dispatcher -----------------------------------------------------------


def test_get_backend_returns_codex_when_named():
    config = HarbormasterConfig()
    config.backends["codex"] = BackendConfig(binary="codex")
    backend = get_backend(config, "codex")
    assert isinstance(backend, CodexBackend)


def test_get_backend_returns_none_for_unknown_name():
    config = HarbormasterConfig()
    assert get_backend(config, "ghost-backend") is None


def test_get_backend_returns_none_when_disabled():
    config = HarbormasterConfig()
    config.backends["claude"] = BackendConfig(enabled=False)
    assert get_backend(config, "claude") is None


def test_default_backend_field_default_is_claude():
    config = HarbormasterConfig()
    assert config.default_backend == "claude"
    assert config.backends_for_project == {}


def test_get_backend_for_project_uses_default_when_no_override():
    config = HarbormasterConfig()
    backend = get_backend_for_project(config, "any-project")
    assert backend is not None
    assert backend.name == "claude"


def test_get_backend_for_project_honours_per_project_override():
    config = HarbormasterConfig()
    config.backends["codex"] = BackendConfig(binary="codex")
    config.backends_for_project = {"frontend": "codex"}
    chosen = get_backend_for_project(config, "frontend")
    assert chosen is not None
    assert chosen.name == "codex"


def test_get_backend_for_project_returns_none_when_override_disabled():
    config = HarbormasterConfig()
    config.backends["codex"] = BackendConfig(binary="codex", enabled=False)
    config.backends_for_project = {"frontend": "codex"}
    assert get_backend_for_project(config, "frontend") is None


def test_get_backend_for_project_falls_back_to_default_for_unmapped_project():
    config = HarbormasterConfig()
    config.backends["codex"] = BackendConfig(binary="codex")
    config.backends_for_project = {"frontend": "codex"}
    chosen = get_backend_for_project(config, "backend-svc")
    assert chosen is not None
    assert chosen.name == "claude"

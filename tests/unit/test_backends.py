"""Unit tests for ClaudeBackend (Protocol-tightened in v1.0.0a3).

Exercises ask_local / ask_remote without spawning real claude — subprocess.run
and run_ssh are monkeypatched to return canned output. End-to-end testing
with a real claude shim binary lives in tests/integration/test_e2e_*.py.
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from harbormaster.backends.base import BackendError, BackendResult
from harbormaster.backends.claude import ClaudeBackend
from harbormaster.config import BackendConfig


@pytest.fixture
def backend():
    return ClaudeBackend(BackendConfig())


def _fake_completed_proc(*, returncode: int = 0, stdout: str = "", stderr: str = ""):
    return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)


# ----- ask_local -------------------------------------------------------------


def test_ask_local_returns_backend_result_on_clean_json(backend, monkeypatch, tmp_path: Path):
    def fake_run(cmd, **kw):
        return _fake_completed_proc(stdout='{"result": "Hello world"}')

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = backend.ask_local(cwd=tmp_path, prompt="hi", max_turns=1)
    assert isinstance(result, BackendResult)
    assert result.output == "Hello world"
    assert result.duration_ms >= 0


def test_ask_local_tolerates_login_banner_before_json(backend, monkeypatch, tmp_path: Path):
    def fake_run(cmd, **kw):
        return _fake_completed_proc(
            stdout='Welcome to bash login shell\nMOTD line 2\n{"result": "answer"}'
        )

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = backend.ask_local(cwd=tmp_path, prompt="hi", max_turns=1)
    assert result.output == "answer"


def test_ask_local_raises_backend_error_on_timeout(backend, monkeypatch, tmp_path: Path):
    def fake_run(cmd, **kw):
        raise subprocess.TimeoutExpired(cmd=cmd, timeout=60)

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(BackendError) as excinfo:
        backend.ask_local(cwd=tmp_path, prompt="hi", max_turns=1)
    assert excinfo.value.code == "timeout"


def test_ask_local_raises_backend_error_on_nonzero_exit(backend, monkeypatch, tmp_path: Path):
    def fake_run(cmd, **kw):
        return _fake_completed_proc(returncode=1, stderr="claude: not authenticated")

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(BackendError) as excinfo:
        backend.ask_local(cwd=tmp_path, prompt="hi", max_turns=1)
    assert excinfo.value.code == "exit_nonzero"
    assert "not authenticated" in excinfo.value.message


def test_ask_local_raises_backend_error_on_non_json_stdout(backend, monkeypatch, tmp_path: Path):
    def fake_run(cmd, **kw):
        return _fake_completed_proc(stdout="this is not json at all")

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(BackendError) as excinfo:
        backend.ask_local(cwd=tmp_path, prompt="hi", max_turns=1)
    assert excinfo.value.code == "parse_failure"


def test_ask_local_raises_backend_error_on_empty_result_field(backend, monkeypatch, tmp_path: Path):
    def fake_run(cmd, **kw):
        return _fake_completed_proc(stdout='{"result": "", "other": "irrelevant"}')

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(BackendError) as excinfo:
        backend.ask_local(cwd=tmp_path, prompt="hi", max_turns=1)
    assert excinfo.value.code == "parse_failure"


# ----- ask_remote ------------------------------------------------------------


def test_ask_remote_returns_backend_result(backend, monkeypatch):
    captured = {}

    def fake_run_ssh(host, remote_cmd, *, total_timeout, connect_timeout):
        captured["host"] = host
        captured["remote_cmd"] = remote_cmd
        return _fake_completed_proc(stdout='{"result": "remote answer"}')

    # ClaudeBackend imports run_ssh into its module namespace
    monkeypatch.setattr("harbormaster.backends.claude.run_ssh", fake_run_ssh)
    result = backend.ask_remote(
        host="friday",
        remote_cwd="~/htdocs/myproj",
        prompt="hello",
        max_turns=2,
        connect_timeout=10,
        total_timeout=60,
    )
    assert isinstance(result, BackendResult)
    assert result.output == "remote answer"
    assert captured["host"] == "friday"
    assert "cd '~/htdocs/myproj'" in captured["remote_cmd"]


def test_ask_remote_raises_on_ssh_layer_failure(backend, monkeypatch):
    def fake_run_ssh(host, remote_cmd, **kw):
        return _fake_completed_proc(
            returncode=255,
            stderr="ssh: connect to host friday port 22: Connection refused",
        )

    monkeypatch.setattr("harbormaster.backends.claude.run_ssh", fake_run_ssh)
    with pytest.raises(BackendError) as excinfo:
        backend.ask_remote(
            host="friday", remote_cwd="~/htdocs/x", prompt="hi",
            max_turns=1, connect_timeout=10, total_timeout=60,
        )
    assert excinfo.value.code == "ssh_error"


def test_ask_remote_raises_on_remote_exit_nonzero(backend, monkeypatch):
    """SSH succeeded but remote claude returned non-zero — that's exit_nonzero,
    not ssh_error. Distinguishes 'reach the host' from 'host did the thing'."""
    def fake_run_ssh(host, remote_cmd, **kw):
        return _fake_completed_proc(returncode=2, stderr="claude: rate limited")

    monkeypatch.setattr("harbormaster.backends.claude.run_ssh", fake_run_ssh)
    with pytest.raises(BackendError) as excinfo:
        backend.ask_remote(
            host="friday", remote_cwd="~/htdocs/x", prompt="hi",
            max_turns=1, connect_timeout=10, total_timeout=60,
        )
    assert excinfo.value.code == "exit_nonzero"


# ----- ask_local_stream (--output-format stream-json) -----------------------


class _FakePopenProc:
    """Stand-in for subprocess.Popen — returns a pre-canned set of stdout
    lines and a fixed return code, so tests can drive the backend's
    streaming parser deterministically.

    stdout/stderr are io.StringIO so they expose the same close() / read()
    interface a real Popen pipe does.
    """

    def __init__(
        self,
        *,
        stdout_lines: list[str],
        stderr: str = "",
        returncode: int = 0,
    ) -> None:
        import io as _io

        self.stdout = _io.StringIO("".join(stdout_lines))
        self.stderr = _io.StringIO(stderr)
        self._returncode = returncode

    def wait(self, timeout=None):  # noqa: ARG002 - Popen-compatible signature
        return self._returncode

    def kill(self):  # pragma: no cover - tests don't exercise the timeout path
        pass


def test_ask_local_stream_yields_assistant_text_blocks(backend, monkeypatch, tmp_path: Path):
    """Stream-json: yield text from assistant messages, drop everything else."""
    lines = [
        '{"type":"system","subtype":"init","session_id":"s1"}\n',
        '{"type":"assistant","message":{"content":[{"type":"text","text":"Hello "}]}}\n',
        '{"type":"assistant","message":{"content":[{"type":"text","text":"world"}]}}\n',
        '{"type":"result","result":"Hello world","duration_ms":42}\n',
    ]

    def fake_popen(cmd, **kw):
        return _FakePopenProc(stdout_lines=lines)

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    chunks = list(backend.ask_local_stream(cwd=tmp_path, prompt="hi", max_turns=1))
    assert chunks == ["Hello ", "world"]


def test_ask_local_stream_skips_tool_use_and_system_messages(backend, monkeypatch, tmp_path: Path):
    """tool_use blocks inside an assistant message are silently dropped —
    only `text` blocks are user-facing."""
    lines = [
        '{"type":"system","subtype":"init"}\n',
        '{"type":"assistant","message":{"content":['
        '{"type":"tool_use","id":"t1","name":"Read","input":{}},'
        '{"type":"text","text":"After tool"}'
        ']}}\n',
    ]
    monkeypatch.setattr(
        subprocess, "Popen",
        lambda *a, **kw: _FakePopenProc(stdout_lines=lines),
    )
    chunks = list(backend.ask_local_stream(cwd=tmp_path, prompt="hi", max_turns=1))
    assert chunks == ["After tool"]


def test_ask_local_stream_raises_parse_error_on_invalid_json(backend, monkeypatch, tmp_path: Path):
    monkeypatch.setattr(
        subprocess, "Popen",
        lambda *a, **kw: _FakePopenProc(
            stdout_lines=['this is not json\n'],
        ),
    )
    with pytest.raises(BackendError) as excinfo:
        list(backend.ask_local_stream(cwd=tmp_path, prompt="hi", max_turns=1))
    assert excinfo.value.code == "parse_failure"


def test_ask_local_stream_raises_exit_nonzero_when_subprocess_fails(backend, monkeypatch, tmp_path: Path):
    """Even though stdout produced valid output, a non-zero rc must surface
    as BackendError after the iterator drains."""
    lines = ['{"type":"assistant","message":{"content":[{"type":"text","text":"partial"}]}}\n']

    def fake_popen(cmd, **kw):
        return _FakePopenProc(
            stdout_lines=lines,
            stderr="something broke",
            returncode=1,
        )

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    with pytest.raises(BackendError) as excinfo:
        list(backend.ask_local_stream(cwd=tmp_path, prompt="hi", max_turns=1))
    assert excinfo.value.code == "exit_nonzero"
    assert "something broke" in str(excinfo.value)


def test_ask_local_stream_uses_stream_json_output_format(backend, monkeypatch, tmp_path: Path):
    """Verify the actual command sent to claude-code uses --output-format
    stream-json (otherwise the parser sees the wrong shape)."""
    captured: dict[str, list[str]] = {}

    def fake_popen(cmd, **kw):
        captured["cmd"] = cmd
        return _FakePopenProc(stdout_lines=[])

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    list(backend.ask_local_stream(cwd=tmp_path, prompt="hi", max_turns=2))

    assert "--output-format" in captured["cmd"]
    fmt_idx = captured["cmd"].index("--output-format")
    assert captured["cmd"][fmt_idx + 1] == "stream-json"
    # claude-code rejects stream-json without --verbose
    assert "--verbose" in captured["cmd"]


def test_ask_remote_quotes_user_inputs(backend, monkeypatch):
    """Adversarial prompt with shell metas must not break the remote command."""
    captured = {}

    def fake_run_ssh(host, remote_cmd, **kw):
        captured["cmd"] = remote_cmd
        return _fake_completed_proc(stdout='{"result": "ok"}')

    monkeypatch.setattr("harbormaster.backends.claude.run_ssh", fake_run_ssh)
    backend.ask_remote(
        host="friday",
        remote_cwd="~/htdocs/x",
        prompt='evil $(rm -rf /) `whoami` "double" \'single\'',
        max_turns=1,
        connect_timeout=10,
        total_timeout=60,
    )
    # The dangerous tokens appear inside single-quoted segments, never bare.
    assert "$(rm -rf /)" in captured["cmd"]  # stays as literal
    # Critically, no unescaped command substitution
    assert "`" in captured["cmd"]  # backtick is in the quoted prompt
    # And the prompt is enclosed (quoted as a single token)
    import shlex as _shlex
    tokens = _shlex.split(captured["cmd"])
    # Last token should be the full prompt as ONE arg
    assert tokens[-1] == 'evil $(rm -rf /) `whoami` "double" \'single\''

"""v12.0.0a1: codex backend token instrumentation.

Closes the v11.0.0a5 deviation (only claude.py was instrumented). Codex's
CLI does not currently emit per-token usage metadata, so the soft-fall
contract is:

  - `ask_local_stream` / `ask_remote_stream` now exist on CodexBackend
    and return an `_StreamWithUsage` carrying a `StreamUsage`.
  - When stdout contains no usage JSON, `has_real_usage` stays False
    and the SSE `usage` event falls back to the v9 chunk-count
    approximation (`approximate: true`).
  - When stdout DOES contain a JSON object with recognised token keys
    (a future codex flag or a wrapper), the line is absorbed (NOT
    yielded as text) and `has_real_usage` becomes True so the SSE
    emitter drops `approximate` and uses real numbers.

Mirrors the shape of `tests/ui/test_backend_token_usage.py`.
"""
from __future__ import annotations

import asyncio
import json
import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from harbormaster.backends.base import StreamUsage, _StreamWithUsage
from harbormaster.backends.codex import CodexBackend
from harbormaster.config import BackendConfig


@pytest.fixture
def cfg() -> BackendConfig:
    return BackendConfig(binary="codex", extra_args=["exec"])


@pytest.fixture
def backend(cfg: BackendConfig) -> CodexBackend:
    return CodexBackend(cfg)


# -- _absorb_optional_usage_line -----------------------------------------


def test_absorb_usage_line_returns_false_for_plain_text() -> None:
    u = StreamUsage()
    assert CodexBackend._absorb_optional_usage_line("hello world\n", u) is False
    assert u.has_real_usage is False


def test_absorb_usage_line_returns_false_for_non_json() -> None:
    u = StreamUsage()
    assert CodexBackend._absorb_optional_usage_line("{not-json\n", u) is False
    assert u.has_real_usage is False


def test_absorb_usage_line_returns_false_for_json_without_usage() -> None:
    """Arbitrary JSON output must remain visible — only lines that
    actually contribute usage data are swallowed."""
    u = StreamUsage()
    line = json.dumps({"answer": "the moon"})
    assert CodexBackend._absorb_optional_usage_line(line, u) is False
    assert u.has_real_usage is False


def test_absorb_usage_line_extracts_top_level_usage() -> None:
    u = StreamUsage()
    line = json.dumps({"usage": {"input_tokens": 12, "output_tokens": 7}})
    assert CodexBackend._absorb_optional_usage_line(line, u) is True
    assert u.input_tokens == 12
    assert u.output_tokens == 7
    assert u.has_real_usage is True


def test_absorb_usage_line_extracts_nested_assistant_usage() -> None:
    u = StreamUsage()
    line = json.dumps({
        "type": "assistant",
        "message": {
            "model": "codex-mini",
            "usage": {"input_tokens": 5, "output_tokens": 3},
        },
    })
    assert CodexBackend._absorb_optional_usage_line(line, u) is True
    assert u.input_tokens == 5
    assert u.model == "codex-mini"


def test_absorb_usage_line_skips_array() -> None:
    """Top-level JSON arrays don't carry usage metadata — treat as text."""
    u = StreamUsage()
    assert CodexBackend._absorb_optional_usage_line("[1, 2, 3]\n", u) is False


# -- ask_local_stream ----------------------------------------------------


def _fake_popen(stdout_lines: list[str], rc: int = 0, stderr: str = "") -> MagicMock:
    """Build a fake Popen returning the given stdout lines + exit code."""
    fake = MagicMock(spec=subprocess.Popen)
    # iter() over the stdout MagicMock yields lines
    stdout_mock = MagicMock()
    stdout_mock.__iter__ = lambda self: iter(stdout_lines)
    stdout_mock.close = MagicMock()
    fake.stdout = stdout_mock
    stderr_mock = MagicMock()
    stderr_mock.read = MagicMock(return_value=stderr)
    stderr_mock.close = MagicMock()
    fake.stderr = stderr_mock
    fake.wait = MagicMock(return_value=rc)
    fake.kill = MagicMock()
    return fake


def test_ask_local_stream_yields_text_lines(
    backend: CodexBackend, tmp_path: Path,
) -> None:
    fake = _fake_popen(["hello\n", "world\n"])
    with patch("harbormaster.backends.codex.subprocess.Popen", return_value=fake):
        stream = backend.ask_local_stream(cwd=tmp_path, prompt="hi", max_turns=1)
        assert isinstance(stream, _StreamWithUsage)
        chunks = list(stream)
    assert chunks == ["hello\n", "world\n"]
    assert stream.usage.has_real_usage is False


def test_ask_local_stream_absorbs_usage_json_line(
    backend: CodexBackend, tmp_path: Path,
) -> None:
    """A stdout line that's a JSON usage record is consumed (not yielded)
    and feeds StreamUsage.has_real_usage = True."""
    usage_line = json.dumps({"usage": {"input_tokens": 30, "output_tokens": 15}}) + "\n"
    fake = _fake_popen(["partial answer\n", usage_line, "tail\n"])
    with patch("harbormaster.backends.codex.subprocess.Popen", return_value=fake):
        stream = backend.ask_local_stream(cwd=tmp_path, prompt="hi", max_turns=1)
        chunks = list(stream)
    assert chunks == ["partial answer\n", "tail\n"]
    assert stream.usage.has_real_usage is True
    assert stream.usage.input_tokens == 30
    assert stream.usage.output_tokens == 15


def test_ask_local_stream_passes_arbitrary_json_through(
    backend: CodexBackend, tmp_path: Path,
) -> None:
    """JSON that isn't a usage record (e.g. a model returning structured
    output) must remain visible to the caller."""
    json_answer = json.dumps({"answer": 42}) + "\n"
    fake = _fake_popen([json_answer])
    with patch("harbormaster.backends.codex.subprocess.Popen", return_value=fake):
        stream = backend.ask_local_stream(cwd=tmp_path, prompt="hi", max_turns=1)
        chunks = list(stream)
    assert chunks == [json_answer]
    assert stream.usage.has_real_usage is False


def test_ask_local_stream_raises_on_missing_binary(
    backend: CodexBackend, tmp_path: Path,
) -> None:
    from harbormaster.backends.base import BackendError

    with patch(
        "harbormaster.backends.codex.subprocess.Popen",
        side_effect=FileNotFoundError("not found"),
    ), pytest.raises(BackendError) as exc:
        backend.ask_local_stream(cwd=tmp_path, prompt="hi", max_turns=1)
    assert exc.value.code == "exit_nonzero"


def test_ask_local_stream_raises_on_nonzero_exit(
    backend: CodexBackend, tmp_path: Path,
) -> None:
    from harbormaster.backends.base import BackendError

    fake = _fake_popen(["partial\n"], rc=2, stderr="boom")
    with patch("harbormaster.backends.codex.subprocess.Popen", return_value=fake):
        stream = backend.ask_local_stream(cwd=tmp_path, prompt="hi", max_turns=1)
        with pytest.raises(BackendError) as exc:
            list(stream)
    assert exc.value.code == "exit_nonzero"


# -- ask_remote_stream ---------------------------------------------------


def test_ask_remote_stream_yields_text(backend: CodexBackend) -> None:
    fake = _fake_popen(["remote line 1\n", "remote line 2\n"])
    with patch(
        "harbormaster.backends.codex.subprocess.Popen", return_value=fake,
    ), patch(
        "harbormaster.ssh.build_ssh_argv",
        return_value=["ssh", "myhost", "echo hi"],
    ):
        stream = backend.ask_remote_stream(
            host="myhost",
            remote_cwd="/srv/app",
            prompt="hi",
            max_turns=1,
            connect_timeout=5,
            total_timeout=30,
        )
        chunks = list(stream)
    assert chunks == ["remote line 1\n", "remote line 2\n"]
    assert stream.usage.has_real_usage is False


def test_ask_remote_stream_maps_ssh_failure(backend: CodexBackend) -> None:
    from harbormaster.backends.base import BackendError

    fake = _fake_popen([], rc=255, stderr="Connection refused")
    with patch(
        "harbormaster.backends.codex.subprocess.Popen", return_value=fake,
    ), patch(
        "harbormaster.ssh.build_ssh_argv",
        return_value=["ssh", "myhost", "echo hi"],
    ):
        stream = backend.ask_remote_stream(
            host="myhost",
            remote_cwd="/srv/app",
            prompt="hi",
            max_turns=1,
            connect_timeout=5,
            total_timeout=30,
        )
        with pytest.raises(BackendError) as exc:
            list(stream)
    assert exc.value.code == "ssh_error"


# -- SSE integration: codex stream flows through usage emitter -----------


@pytest.mark.asyncio
async def test_codex_stream_falls_back_to_approximate_in_sse() -> None:
    """When codex is the backend (no real usage metadata), the SSE
    `usage` event must emit `approximate: true` with chunk counts."""
    from harbormaster.ui.routes import _emit_chunks_then_result

    u = StreamUsage()  # has_real_usage stays False

    def text_gen() -> Any:
        yield "alpha"
        yield "beta"

    wrapped = _StreamWithUsage(text_gen(), u)
    received: list[dict[str, Any]] = []
    async for evt in _emit_chunks_then_result(wrapped):
        received.append(evt)

    usage_events = [e for e in received if e["event"] == "usage"]
    assert len(usage_events) == 1
    payload = json.loads(usage_events[0]["data"])
    assert payload.get("approximate") is True
    assert payload["output_chunks"] == 2
    assert "input_tokens" not in payload


@pytest.mark.asyncio
async def test_codex_stream_with_real_usage_drops_approximate() -> None:
    """If a future codex wrapper does emit a JSON usage record (and
    `_absorb_optional_usage_line` picks it up), the SSE `usage` event
    must DROP the approximate flag and carry the real numbers — exactly
    like the claude path."""
    from harbormaster.ui.routes import _emit_chunks_then_result

    u = StreamUsage(
        input_tokens=8, output_tokens=4,
        model="codex-mini", has_real_usage=True,
    )

    def text_gen() -> Any:
        yield "x"

    wrapped = _StreamWithUsage(text_gen(), u)
    received: list[dict[str, Any]] = []
    async for evt in _emit_chunks_then_result(wrapped):
        received.append(evt)

    payload = json.loads(
        next(e for e in received if e["event"] == "usage")["data"],
    )
    assert payload["input_tokens"] == 8
    assert payload["output_tokens"] == 4
    assert payload["model"] == "codex-mini"
    assert "approximate" not in payload


# -- Smoke ---------------------------------------------------------------


def test_codex_backend_now_supports_streaming_protocol() -> None:
    """Closes the v11.0.0a5 deviation: the dispatcher's
    `hasattr(backend, "ask_local_stream")` gate now passes for codex."""
    cfg = BackendConfig(binary="codex")
    b = CodexBackend(cfg)
    assert hasattr(b, "ask_local_stream")
    assert hasattr(b, "ask_remote_stream")


def test_streamusage_and_wrapper_reexported_from_claude_for_back_compat() -> None:
    """v12.0.0a1 lifted StreamUsage and _StreamWithUsage into base.py.
    Re-exports from claude.py keep existing callers (and v11 tests)
    working — verify the symbol identity is preserved."""
    from harbormaster.backends.base import StreamUsage as Base_SU
    from harbormaster.backends.base import _StreamWithUsage as Base_W
    from harbormaster.backends.claude import StreamUsage as Claude_SU
    from harbormaster.backends.claude import _StreamWithUsage as Claude_W
    assert Base_SU is Claude_SU
    assert Base_W is Claude_W


# Async helper to keep the asyncio import live (mirrors v11 test file).
def test_asyncio_importable() -> None:
    assert asyncio is not None

"""Backend Protocol and shared types.

A Backend asks a question against a project — locally as a subprocess and
remotely over SSH — and returns a uniform `BackendResult`. The Protocol is
deliberately minimal so non-Claude backends (codex, aider, gemini, local
llama-server) can implement it without exposing transport / parsing details
to callers.

Failure mode contract: methods raise `BackendError(code=...)` instead of
returning a result with an ok flag. Callers in `tools/_helpers.py` map
exceptions back to user-visible 'Error: ...' strings at the MCP boundary.
"""
from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class BackendResult:
    """Successful backend invocation.

    Truncation policy lives at the tool boundary (`_helpers._truncate`),
    not in the backend — this dataclass is the raw subagent answer.
    """

    output: str
    duration_ms: int


class BackendError(Exception):
    """Backend failure with a stable code for callers to dispatch on.

    Codes:
      - 'timeout'        — local subprocess or SSH exceeded its timeout
      - 'exit_nonzero'   — subagent process returned a non-zero exit
      - 'parse_failure'  — stdout did not contain a valid result payload
      - 'ssh_error'      — SSH layer failed (refused / auth / unknown host)
      - 'auth_failure'   — backend-specific auth (Anthropic seat) failed
    """

    def __init__(self, message: str, code: str) -> None:
        super().__init__(message)
        self.message = message
        self.code = code

    def __str__(self) -> str:
        return self.message


@dataclass
class StreamUsage:
    """Backend-reported usage captured during streaming.

    Originally introduced in v11.0.0a5 inside `claude.py`; lifted to
    `backends/base.py` in v12.0.0a1 so non-Claude backends (codex) can
    reuse the same shape and the SSE `usage` event emitter only has to
    look for one duck-typed attribute (`.has_real_usage`).

    Populated as the stream progresses. After the iterator is fully
    drained, this object holds final values. Callers (the SSE `usage`
    event emitter) read fields on completion; mid-stream reads return
    whatever was reported up to that point.

    `has_real_usage` distinguishes "backend gave no metadata"
    (callers fall back to the chunk-count approximation) from
    "backend reported zero".
    """

    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0
    model: str | None = None
    has_real_usage: bool = field(default=False)

    def merge_message_usage(self, msg: dict[str, object]) -> None:
        """Pull usage fields from one parsed stream-json line.

        The Claude `assistant` message shape carries usage in
        `message.usage`; the `result` summary carries it at top level.
        Both are absorbed by the same code path. Other backends (codex)
        whose CLI doesn't expose comparable metadata simply never call
        this and `has_real_usage` stays False.
        """
        message = msg.get("message")
        if isinstance(message, dict):
            usage = message.get("usage")
            if isinstance(usage, dict):
                self._absorb_usage_block(usage)
            model = message.get("model")
            if isinstance(model, str):
                self.model = model
        usage = msg.get("usage")
        if isinstance(usage, dict):
            self._absorb_usage_block(usage)

    def _absorb_usage_block(self, usage: dict[str, object]) -> None:
        for key in (
            "input_tokens",
            "output_tokens",
            "cache_creation_input_tokens",
            "cache_read_input_tokens",
        ):
            v = usage.get(key)
            if isinstance(v, int):
                setattr(self, key, v)
                self.has_real_usage = True


class _StreamWithUsage(Iterator[str]):
    """Wrap a text-delta iterator + a side-channel `StreamUsage`.

    Iterating yields the underlying text deltas. Once the wrapped
    iterator is exhausted, `self.usage` holds the final captured usage
    (if the backend reported any). Callers who don't care about usage
    iterate as if it were a plain `Iterator[str]`.

    Lifted from `backends/claude.py` to `backends/base.py` in v12.0.0a1
    so codex (and future backends) can wrap their own iterators with
    the same shape.
    """

    def __init__(self, source: Iterator[str], usage: StreamUsage) -> None:
        self._source = source
        self.usage = usage

    def __iter__(self) -> Iterator[str]:
        return self

    def __next__(self) -> str:
        return next(self._source)


class Backend(Protocol):
    """Pluggable contract for asking a project question."""

    name: str
    # Every concrete backend keeps a reference to its config block —
    # exposed through the Protocol so callers can read shared
    # `BackendConfig` fields like `output_word_cap` without type-narrowing
    # to a specific implementation.
    cfg: BackendConfig

    def ask_local(
        self,
        *,
        cwd: Path,
        prompt: str,
        max_turns: int,
        model: str | None = None,
    ) -> BackendResult: ...

    def ask_remote(
        self,
        *,
        host: str,
        remote_cwd: str,
        prompt: str,
        max_turns: int,
        connect_timeout: int,
        total_timeout: int,
        model: str | None = None,
    ) -> BackendResult: ...


# Forward import lives at the bottom so the Protocol body can reference
# BackendConfig as a string. Avoids a top-level cycle: config imports
# nothing from backends, and backends.base must remain import-cheap.
from harbormaster.config import BackendConfig  # noqa: E402

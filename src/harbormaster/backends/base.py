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

from dataclasses import dataclass
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
    ) -> BackendResult: ...


# Forward import lives at the bottom so the Protocol body can reference
# BackendConfig as a string. Avoids a top-level cycle: config imports
# nothing from backends, and backends.base must remain import-cheap.
from harbormaster.config import BackendConfig  # noqa: E402

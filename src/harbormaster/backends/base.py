"""Backend Protocol and shared types.

A Backend knows how to ask a question against a project — locally as a
subprocess and remotely as a shell command sent over SSH. The Protocol keeps
the contract minimal so non-Claude backends (codex, aider, gemini) can drop in.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class BackendResult:
    output: str
    truncated: bool
    duration_ms: int


class BackendError(Exception):
    """Backend failure with a stable code for callers to dispatch on."""

    def __init__(self, message: str, code: str) -> None:
        super().__init__(message)
        self.message = message
        self.code = code  # 'timeout' | 'exit_nonzero' | 'parse_failure' | 'auth_failure'

    def __str__(self) -> str:
        return self.message


class Backend(Protocol):
    """Pluggable backend contract."""

    name: str

    def ask_local(self, *, cwd: Path, prompt: str, max_turns: int) -> str: ...

    def build_remote_command(
        self, *, remote_cwd: str, prompt: str, max_turns: int
    ) -> str: ...

    def parse_remote_stdout(self, stdout: str) -> str: ...

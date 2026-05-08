"""Claude Code (`claude -p`) backend — the default for v1.0."""
from __future__ import annotations

import json
import shlex
import subprocess
from pathlib import Path

from harbormaster.backends.base import BackendError
from harbormaster.config import BackendConfig


class ClaudeBackend:
    name = "claude"

    def __init__(self, cfg: BackendConfig) -> None:
        self.cfg = cfg

    def ask_local(self, *, cwd: Path, prompt: str, max_turns: int) -> str:
        cmd = [
            self.cfg.binary, "-p",
            "--permission-mode", "bypassPermissions",
            "--max-turns", str(max_turns),
            "--output-format", "json",
            prompt,
        ]
        try:
            proc = subprocess.run(
                cmd, cwd=str(cwd), capture_output=True, text=True,
                timeout=self.cfg.timeout_local,
            )
        except subprocess.TimeoutExpired as e:
            raise BackendError(
                f"timeout: claude -p exceeded {self.cfg.timeout_local}s",
                code="timeout",
            ) from e

        if proc.returncode != 0:
            stderr_tail = proc.stderr[-500:] if proc.stderr else "(no stderr)"
            raise BackendError(
                f"claude -p exit {proc.returncode}: {stderr_tail}",
                code="exit_nonzero",
            )
        return self.parse_remote_stdout(proc.stdout)

    def build_remote_command(
        self, *, remote_cwd: str, prompt: str, max_turns: int
    ) -> str:
        qcwd = shlex.quote(remote_cwd)
        qprompt = shlex.quote(prompt)
        qbin = shlex.quote(self.cfg.binary)
        qmaxturns = shlex.quote(str(max_turns))
        return (
            f"cd {qcwd} && {qbin} -p "
            f"--permission-mode bypassPermissions "
            f"--max-turns {qmaxturns} "
            f"--output-format json "
            f"-- {qprompt}"
        )

    def parse_remote_stdout(self, stdout: str) -> str:
        """Tolerate leading bash-login-shell banner noise: locate first valid JSON."""
        if not stdout:
            raise BackendError("claude -p returned empty stdout", code="parse_failure")
        payload: dict | None = None
        try:
            payload = json.loads(stdout.strip())
        except json.JSONDecodeError:
            idx = stdout.find("{")
            while idx != -1:
                try:
                    payload = json.loads(stdout[idx:])
                    break
                except json.JSONDecodeError:
                    idx = stdout.find("{", idx + 1)
        if payload is None:
            raise BackendError(
                f"claude -p returned non-JSON: {stdout[:300]}",
                code="parse_failure",
            )
        result = payload.get("result") or payload.get("response") or ""
        if not result:
            raise BackendError(
                f"claude -p returned empty result. Payload keys: {list(payload.keys())}",
                code="parse_failure",
            )
        return result

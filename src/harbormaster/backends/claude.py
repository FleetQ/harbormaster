"""Claude Code (`claude -p`) backend — the default for v1.0."""
from __future__ import annotations

import json
import shlex
import subprocess
import time
from pathlib import Path

from harbormaster.backends.base import BackendError, BackendResult
from harbormaster.config import BackendConfig
from harbormaster.ssh import SshTimeoutError, diagnose_ssh_failure, run_ssh


class ClaudeBackend:
    """Spawns `claude -p` locally or over SSH and parses the JSON output.

    The remote command builder and the stdout parser are private — callers
    only see `ask_local` / `ask_remote` returning `BackendResult`. Remote
    execution lives entirely inside this class so swapping backends doesn't
    require rewriting the SSH glue.
    """

    name = "claude"

    def __init__(self, cfg: BackendConfig) -> None:
        self.cfg = cfg

    # ----- public Protocol surface ------------------------------------------

    def ask_local(self, *, cwd: Path, prompt: str, max_turns: int) -> BackendResult:
        cmd = [
            self.cfg.binary, "-p",
            "--permission-mode", "bypassPermissions",
            "--max-turns", str(max_turns),
            "--output-format", "json",
            prompt,
        ]
        start = time.monotonic()
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
        output = self._parse_stdout(proc.stdout)
        duration_ms = int((time.monotonic() - start) * 1000)
        return BackendResult(output=output, duration_ms=duration_ms)

    def ask_remote(
        self,
        *,
        host: str,
        remote_cwd: str,
        prompt: str,
        max_turns: int,
        connect_timeout: int,
        total_timeout: int,
    ) -> BackendResult:
        remote_cmd = self._build_remote_command(remote_cwd, prompt, max_turns)
        start = time.monotonic()
        try:
            proc = run_ssh(
                host, remote_cmd,
                total_timeout=total_timeout,
                connect_timeout=connect_timeout,
            )
        except SshTimeoutError as e:
            raise BackendError(str(e), code="timeout") from e

        ssh_err = diagnose_ssh_failure(host, proc)
        if ssh_err:
            raise BackendError(ssh_err, code="ssh_error")
        if proc.returncode != 0:
            stderr_tail = (proc.stderr or "")[-500:]
            raise BackendError(
                f"remote claude -p exit {proc.returncode}: {stderr_tail}",
                code="exit_nonzero",
            )
        output = self._parse_stdout(proc.stdout)
        duration_ms = int((time.monotonic() - start) * 1000)
        return BackendResult(output=output, duration_ms=duration_ms)

    # ----- private helpers --------------------------------------------------

    def _build_remote_command(
        self, remote_cwd: str, prompt: str, max_turns: int
    ) -> str:
        """Compose the bash command sent to the remote host. All user-supplied
        values pass through shlex.quote before assembly."""
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

    def _parse_stdout(self, stdout: str) -> str:
        """Tolerate leading bash-login-shell banner noise: locate first valid
        JSON object, then extract `result` (or fallback `response`) field."""
        if not stdout:
            raise BackendError("claude -p returned empty stdout", code="parse_failure")
        payload: dict[str, object] | None = None
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
        result_obj = payload.get("result") or payload.get("response")
        if not isinstance(result_obj, str) or not result_obj:
            raise BackendError(
                f"claude -p returned empty/non-string result. Payload keys: {list(payload.keys())}",
                code="parse_failure",
            )
        return result_obj

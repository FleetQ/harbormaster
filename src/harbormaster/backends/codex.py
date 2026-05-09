"""OpenAI Codex (`codex`) backend (v2.0.0a3).

Mirrors `ClaudeBackend` for the non-streaming subset of the Backend
Protocol (`ask_local`, `ask_remote`). Streaming support is deliberately
omitted in this first cut — Codex's CLI doesn't yet expose a
JSON-stream comparable to `claude --output-format stream-json`. When
streaming is needed, the dispatcher in `_helpers.py` already gates on
`hasattr(backend, "ask_local_stream")`, so the SSE path will fall
through to the buffered result instead of erroring out.

The output is taken from stdout verbatim — we don't try to parse a
JSON envelope, since the codex CLI shape varies across versions and
configurations. If the operator wants structured output, they can
configure `extra_args = ["--output", "json", ...]` and post-process
on the consumer side.

Soft-fail: if the `codex` binary isn't on $PATH, `ask_local` raises a
`BackendError(code="exit_nonzero")` with the standard FileNotFoundError
message — it does NOT crash on import or on backend construction.
"""

from __future__ import annotations

import shlex
import subprocess
import time
from pathlib import Path

from harbormaster.backends.base import BackendError, BackendResult
from harbormaster.config import BackendConfig
from harbormaster.ssh import SshTimeoutError, diagnose_ssh_failure, run_ssh


class CodexBackend:
    """Spawns OpenAI Codex (`codex`) locally or over SSH.

    The Backend Protocol surface is `ask_local` + `ask_remote`. Both
    take the prompt as the final positional argument after any
    configured `extra_args`. Output is the raw stdout of the codex
    process.
    """

    name = "codex"

    def __init__(self, cfg: BackendConfig) -> None:
        self.cfg = cfg

    # ----- public Protocol surface ------------------------------------------

    def ask_local(self, *, cwd: Path, prompt: str, max_turns: int) -> BackendResult:
        cmd = [self.cfg.binary, *self.cfg.extra_args, prompt]
        start = time.monotonic()
        try:
            proc = subprocess.run(
                cmd,
                cwd=str(cwd),
                capture_output=True,
                text=True,
                timeout=self.cfg.timeout_local,
                check=False,
            )
        except subprocess.TimeoutExpired as e:
            raise BackendError(
                f"timeout: {self.cfg.binary} exceeded {self.cfg.timeout_local}s",
                code="timeout",
            ) from e
        except FileNotFoundError as e:
            raise BackendError(
                f"codex binary not found: {self.cfg.binary!r}. Install Codex "
                f"or set [backends.codex].binary to a valid path.",
                code="exit_nonzero",
            ) from e

        if proc.returncode != 0:
            stderr_tail = proc.stderr[-500:] if proc.stderr else "(no stderr)"
            raise BackendError(
                f"{self.cfg.binary} exit {proc.returncode}: {stderr_tail}",
                code="exit_nonzero",
            )
        output = self._sanitize_output(proc.stdout)
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
        remote_cmd = self._build_remote_command(remote_cwd, prompt)
        start = time.monotonic()
        try:
            proc = run_ssh(
                host,
                remote_cmd,
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
                f"remote {self.cfg.binary} exit {proc.returncode}: {stderr_tail}",
                code="exit_nonzero",
            )
        output = self._sanitize_output(proc.stdout)
        duration_ms = int((time.monotonic() - start) * 1000)
        return BackendResult(output=output, duration_ms=duration_ms)

    # ----- private helpers --------------------------------------------------

    def _build_remote_command(self, remote_cwd: str, prompt: str) -> str:
        """Compose the bash command sent to the remote host. All
        user-supplied values pass through `shlex.quote` before assembly."""
        qcwd = shlex.quote(remote_cwd)
        qprompt = shlex.quote(prompt)
        qbin = shlex.quote(self.cfg.binary)
        qextra = " ".join(shlex.quote(a) for a in self.cfg.extra_args)
        space = " " if qextra else ""
        return f"cd {qcwd} && {qbin}{space}{qextra} -- {qprompt}"

    @staticmethod
    def _sanitize_output(stdout: str) -> str:
        """Trim trailing whitespace and reject empty stdout. Codex's
        stdout is plain text by default — we don't try to extract any
        JSON envelope (some configurations emit structured output, but
        that's the operator's call to post-process). Empty stdout is
        treated as a parse failure since the user prompt should always
        produce *something*."""
        out = stdout.rstrip()
        if not out:
            raise BackendError(
                "codex returned empty stdout — check the binary and "
                "extra_args; you may need a subcommand like 'exec'.",
                code="parse_failure",
            )
        return out

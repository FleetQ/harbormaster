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

import json
import shlex
import subprocess
import time
from collections.abc import Iterator
from pathlib import Path

from harbormaster.backends.base import (
    BackendError,
    BackendResult,
    StreamUsage,
    _StreamWithUsage,
)
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

    # ----- streaming surface (v12.0.0a1) ------------------------------------

    def ask_local_stream(
        self, *, cwd: Path, prompt: str, max_turns: int,
    ) -> Iterator[str]:
        """Stream codex's stdout as text deltas, line-by-line.

        Codex (`codex exec ...`) emits plain text on stdout — there is
        no per-message JSON envelope comparable to claude's
        `--output-format stream-json`. We therefore yield each non-empty
        stdout line as a delta so the SSE pipeline can incrementally
        forward output instead of buffering the whole answer.

        Token usage: best-effort only. If a line happens to parse as a
        JSON object that contains `input_tokens` / `output_tokens` /
        `model` keys (some codex configurations / wrappers emit a final
        usage record), we feed it into `StreamUsage`. Otherwise
        `has_real_usage` stays False and the SSE `usage` event falls
        back to the chunk-count approximation (with `approximate: true`).
        Lines that look like JSON usage records are NOT yielded as text
        deltas to avoid leaking metadata into the visible answer.

        Failure modes mirror `ask_local`:
          - timeout → BackendError(code='timeout') after killing the subprocess
          - non-zero exit → BackendError(code='exit_nonzero')
          - missing binary → BackendError(code='exit_nonzero')

        The iterator MUST be drained so the subprocess is reaped.
        """
        cmd = [self.cfg.binary, *self.cfg.extra_args, prompt]
        usage = StreamUsage()
        try:
            proc = subprocess.Popen(
                cmd, cwd=str(cwd),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
            )
        except FileNotFoundError as e:
            raise BackendError(
                f"codex binary not found: {self.cfg.binary!r}. Install Codex "
                f"or set [backends.codex].binary to a valid path.",
                code="exit_nonzero",
            ) from e
        deadline = time.monotonic() + self.cfg.timeout_local
        assert proc.stdout is not None  # noqa: S101 - PIPE was requested

        def _gen() -> Iterator[str]:
            try:
                assert proc.stdout is not None  # noqa: S101
                for line in proc.stdout:
                    if time.monotonic() > deadline:
                        proc.kill()
                        proc.wait(timeout=2)
                        raise BackendError(
                            f"timeout: codex exceeded {self.cfg.timeout_local}s",
                            code="timeout",
                        )
                    if not line:
                        continue
                    if self._absorb_optional_usage_line(line, usage):
                        continue
                    yield line
            finally:
                stderr_tail = ""
                if proc.stderr is not None:
                    stderr_tail = (proc.stderr.read() or "")[-500:]
                    proc.stderr.close()
                if proc.stdout is not None:
                    proc.stdout.close()
                try:
                    rc = proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    rc = proc.wait()
                if rc != 0:
                    raise BackendError(
                        f"codex exit {rc}: {stderr_tail or '(no stderr)'}",
                        code="exit_nonzero",
                    )

        return _StreamWithUsage(_gen(), usage)

    def ask_remote_stream(
        self, *,
        host: str,
        remote_cwd: str,
        prompt: str,
        max_turns: int,
        connect_timeout: int,
        total_timeout: int,
    ) -> Iterator[str]:
        """SSH variant of ask_local_stream — pipe codex stdout through
        ssh and yield lines as deltas as they arrive. Same usage-soft-fall
        contract as the local path.
        """
        from harbormaster.ssh import build_ssh_argv

        remote_cmd = self._build_remote_command(remote_cwd, prompt)
        argv = build_ssh_argv(host, remote_cmd, connect_timeout=connect_timeout)
        ssh_idx = argv.index("ssh")
        argv = [*argv[:ssh_idx + 1], "-T", "-q", *argv[ssh_idx + 1:]]

        usage = StreamUsage()
        proc = subprocess.Popen(
            argv,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        deadline = time.monotonic() + total_timeout
        assert proc.stdout is not None  # noqa: S101 - PIPE was requested

        def _gen() -> Iterator[str]:
            try:
                assert proc.stdout is not None  # noqa: S101
                for line in proc.stdout:
                    if time.monotonic() > deadline:
                        proc.kill()
                        proc.wait(timeout=2)
                        raise BackendError(
                            f"timeout: ssh+codex exceeded {total_timeout}s",
                            code="timeout",
                        )
                    if not line:
                        continue
                    if self._absorb_optional_usage_line(line, usage):
                        continue
                    yield line
            finally:
                stderr_tail = ""
                if proc.stderr is not None:
                    stderr_tail = (proc.stderr.read() or "")[-500:]
                    proc.stderr.close()
                if proc.stdout is not None:
                    proc.stdout.close()
                try:
                    rc = proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    rc = proc.wait()
                if rc == 255:
                    raise BackendError(
                        f"ssh to {host!r} failed (rc=255): {stderr_tail or '(no stderr)'}",
                        code="ssh_error",
                    )
                if rc != 0:
                    raise BackendError(
                        f"remote codex exit {rc}: {stderr_tail or '(no stderr)'}",
                        code="exit_nonzero",
                    )

        return _StreamWithUsage(_gen(), usage)

    @staticmethod
    def _absorb_optional_usage_line(line: str, usage: StreamUsage) -> bool:
        """If `line` parses as a JSON object whose top-level OR nested
        `usage` block contains recognised token keys, feed it into the
        passed StreamUsage and return True (caller drops the line).
        Otherwise return False (caller yields the line as a text delta).

        This is best-effort: codex's CLI doesn't currently expose token
        metadata in a documented format, but some wrappers / future
        versions might. We tolerate any input — non-JSON lines and
        JSON without usage keys are treated as text.
        """
        stripped = line.strip()
        if not stripped or stripped[0] not in "{[":
            return False
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError:
            return False
        if not isinstance(parsed, dict):
            return False
        before = usage.has_real_usage
        usage.merge_message_usage(parsed)
        # Only swallow the line if it actually contributed usage data —
        # arbitrary JSON output (a model returning a json answer) must
        # still be visible.
        return usage.has_real_usage and not before

"""Claude Code (`claude -p`) backend — the default for v1.0."""
from __future__ import annotations

import json
import shlex
import subprocess
import time
from collections.abc import Iterator
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

    def ask_local_stream(
        self, *, cwd: Path, prompt: str, max_turns: int,
    ) -> Iterator[str]:
        """Stream-json variant of ask_local: yields assistant text chunks
        as `claude -p` produces them, instead of buffering the entire
        response.

        Uses `--output-format stream-json` which emits one JSON object
        per line on stdout. Each object has a `type` field; we forward
        the text contents of `assistant` messages and ignore everything
        else (tool calls, system messages, the final `result` summary).

        Failure modes match ask_local:
          - timeout → BackendError(code='timeout') after killing the subprocess
          - non-zero exit → BackendError(code='exit_nonzero')
          - malformed line → BackendError(code='parse_failure')

        The iterator is exhausted when stdout closes; callers MUST drain
        it (or use a context that does) so the subprocess is reaped.
        """
        cmd = [
            self.cfg.binary, "-p",
            "--permission-mode", "bypassPermissions",
            "--max-turns", str(max_turns),
            "--output-format", "stream-json",
            "--verbose",  # stream-json requires --verbose in current claude-code
            prompt,
        ]
        proc = subprocess.Popen(
            cmd, cwd=str(cwd),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,  # line-buffered
        )
        deadline = time.monotonic() + self.cfg.timeout_local
        assert proc.stdout is not None  # noqa: S101 - PIPE was requested

        try:
            for line in proc.stdout:
                if time.monotonic() > deadline:
                    proc.kill()
                    proc.wait(timeout=2)
                    raise BackendError(
                        f"timeout: claude -p exceeded {self.cfg.timeout_local}s",
                        code="timeout",
                    )
                line = line.strip()
                if not line:
                    continue
                yield from self._extract_assistant_text(line)
        finally:
            # Always drain stderr + reap the subprocess so we don't leak
            # zombies even when the caller stops iterating early.
            stderr_tail = ""
            if proc.stderr is not None:
                stderr_tail = (proc.stderr.read() or "")[-500:]
                proc.stderr.close()
            proc.stdout.close()
            try:
                rc = proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                rc = proc.wait()
            if rc != 0:
                raise BackendError(
                    f"claude -p exit {rc}: {stderr_tail or '(no stderr)'}",
                    code="exit_nonzero",
                )

    @staticmethod
    def _extract_assistant_text(line: str) -> Iterator[str]:
        """Parse one stream-json line and yield text deltas if it is an
        assistant message. Anything else (system, tool_use, result) is
        silently skipped — those are not user-facing tokens.

        Tolerates malformed lines (logs warnings via BackendError only
        when the upstream contract is clearly broken).
        """
        try:
            msg = json.loads(line)
        except json.JSONDecodeError as e:
            raise BackendError(
                f"claude -p stream-json line is not JSON: {line[:200]}",
                code="parse_failure",
            ) from e
        if not isinstance(msg, dict):
            return
        if msg.get("type") != "assistant":
            return
        message = msg.get("message")
        if not isinstance(message, dict):
            return
        content = message.get("content")
        if not isinstance(content, list):
            return
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") != "text":
                continue
            text = block.get("text")
            if isinstance(text, str) and text:
                yield text

    def ask_remote_stream(
        self, *,
        host: str,
        remote_cwd: str,
        prompt: str,
        max_turns: int,
        connect_timeout: int,
        total_timeout: int,
    ) -> Iterator[str]:
        """SSH variant of ask_local_stream — pipe stream-json output through
        ssh and yield assistant text deltas as they arrive.

        Defenses against ssh-noise that can land on stdout:
          - `ssh -T -q` (no PTY, suppressed banner) — appended via
            build_ssh_argv shape
          - filter lines that don't parse as JSON; only yield from
            recognised assistant `text` blocks. Login banners / MOTD
            from the remote shell get silently dropped instead of
            polluting the SSE chunk stream.

        Failure modes:
          - SSH-layer error (rc 255: connection refused / auth) →
            BackendError(code='ssh_error')
          - Local-side timeout exceeded → BackendError(code='timeout')
            with the ssh subprocess killed and reaped
          - Remote claude exit non-zero → BackendError(code='exit_nonzero')
            with stderr tail

        The `finally` block always reaps the subprocess so we don't
        leak zombies if the consumer breaks out of iteration early.
        """
        from harbormaster.ssh import build_ssh_argv

        # Build the same remote command shape as ask_remote, but with
        # stream-json output. shlex.quote on every interpolated value.
        qcwd = shlex.quote(remote_cwd)
        qprompt = shlex.quote(prompt)
        qbin = shlex.quote(self.cfg.binary)
        qmaxturns = shlex.quote(str(max_turns))
        remote_cmd = (
            f"cd {qcwd} && {qbin} -p "
            f"--permission-mode bypassPermissions "
            f"--max-turns {qmaxturns} "
            f"--output-format stream-json --verbose "
            f"-- {qprompt}"
        )

        argv = build_ssh_argv(host, remote_cmd, connect_timeout=connect_timeout)
        # `-T` (no PTY) + `-q` (quiet) keep ssh's own banner / motd off
        # stdout. Insert right after the `ssh` token.
        ssh_idx = argv.index("ssh")
        argv = [*argv[:ssh_idx + 1], "-T", "-q", *argv[ssh_idx + 1:]]

        proc = subprocess.Popen(
            argv,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        deadline = time.monotonic() + total_timeout
        assert proc.stdout is not None  # noqa: S101 - PIPE was requested

        try:
            for line in proc.stdout:
                if time.monotonic() > deadline:
                    proc.kill()
                    proc.wait(timeout=2)
                    raise BackendError(
                        f"timeout: ssh+claude exceeded {total_timeout}s",
                        code="timeout",
                    )
                line = line.strip()
                if not line:
                    continue
                # Tolerate non-JSON lines (login banner / shell prompt
                # / ssh status messages). Only assistant text deltas
                # reach the caller.
                try:
                    yield from self._extract_assistant_text(line)
                except BackendError as e:
                    if e.code == "parse_failure":
                        # Non-JSON noise; skip silently.
                        continue
                    raise
        finally:
            stderr_tail = ""
            if proc.stderr is not None:
                stderr_tail = (proc.stderr.read() or "")[-500:]
                proc.stderr.close()
            proc.stdout.close()
            try:
                rc = proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                rc = proc.wait()
            if rc == 255:
                # ssh's own non-zero exit — connection refused, auth,
                # host key verification, etc.
                raise BackendError(
                    f"ssh to {host!r} failed (rc=255): {stderr_tail or '(no stderr)'}",
                    code="ssh_error",
                )
            if rc != 0:
                raise BackendError(
                    f"remote claude -p exit {rc}: {stderr_tail or '(no stderr)'}",
                    code="exit_nonzero",
                )

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

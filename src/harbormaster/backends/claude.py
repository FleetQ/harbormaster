"""Claude Code (`claude -p`) backend — the default for v1.0."""
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

# Re-exports (v11 callers + tests imported these names from claude.py;
# v12.0.0a1 lifted the dataclass + wrapper into backends/base.py so
# codex can share the shape. Keep the re-exports so the public symbol
# location stays the same.)
__all__ = ["ClaudeBackend", "StreamUsage", "_StreamWithUsage"]


# v16.0.0a6: per-process registry mapping a Claude `tool_use.id` to
# the running span we opened for it. Populated by
# `_maybe_emit_tool_use_span`, drained by `_maybe_close_tool_result_span`.
# The registry is best-effort — if a `tool_use` lands without a
# matching `tool_result` (e.g. cancelled run), the entry just stays
# pinned until the process restarts. Unbounded growth is bounded
# practically by the dispatch lifetime; harbormaster restarts often
# enough that this is fine for an observability surface.
_TOOL_USE_SPANS: dict[str, object] = {}


def _maybe_emit_tool_use_span(block: dict[str, object]) -> None:
    """Open a child span for a Claude `tool_use` block, if a parent
    dispatch is currently active. Failures are swallowed.
    """
    try:
        from harbormaster.fleetq import (
            current_span_id,
            current_trace_id,
            get_dispatcher_stats,
        )
    except Exception:  # noqa: BLE001  — instrumentation must never raise
        return
    parent = current_span_id()
    if parent is None:
        return  # outside a dispatch → no span to attribute against.
    use_id = block.get("id")
    name = block.get("name")
    if not isinstance(use_id, str) or not isinstance(name, str):
        return
    try:
        span = get_dispatcher_stats().record_start(
            tool=f"claude.tool:{name}",
            parent_span_id=parent,
            trace_id=current_trace_id(),
        )
    except Exception:  # noqa: BLE001
        return
    _TOOL_USE_SPANS[use_id] = span


def _maybe_close_tool_result_span(block: dict[str, object]) -> None:
    """Close the child span previously opened for the matching
    `tool_use.id`. The Claude stream-json `tool_result` block carries
    `tool_use_id` to correlate. Failures are swallowed.
    """
    try:
        from harbormaster.fleetq import get_dispatcher_stats
    except Exception:  # noqa: BLE001
        return
    use_id = block.get("tool_use_id")
    if not isinstance(use_id, str):
        return
    span = _TOOL_USE_SPANS.pop(use_id, None)
    if span is None:
        return
    is_error = bool(block.get("is_error"))
    try:
        get_dispatcher_stats().record_end(span, ok=not is_error)  # type: ignore[arg-type]
    except Exception:  # noqa: BLE001
        return


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

    def _resolve_model(self, model: str | None) -> str | None:
        """v21.0.0a10: resolve a user-supplied model name through the
        backend's aliases + whitelist.

        Returns None when no `--model` arg should be passed to the
        binary (= backend default). Raises BackendError("model_not_allowed")
        when `allowed_models` is non-empty and the resolved id is not in
        the whitelist.
        """
        effective = model or self.cfg.default_model
        if effective is None:
            return None
        full_id = self.cfg.model_aliases.get(effective, effective)
        if self.cfg.allowed_models and full_id not in self.cfg.allowed_models:
            raise BackendError(
                f"model {effective!r} not in allowed_models list",
                code="model_not_allowed",
            )
        return full_id

    def ask_local(
        self,
        *,
        cwd: Path,
        prompt: str,
        max_turns: int,
        model: str | None = None,
    ) -> BackendResult:
        cmd = [self.cfg.binary, "-p"]
        resolved = self._resolve_model(model)
        if resolved:
            cmd += ["--model", resolved]
        cmd += [
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
        model: str | None = None,
    ) -> BackendResult:
        resolved = self._resolve_model(model)
        remote_cmd = self._build_remote_command(
            remote_cwd, prompt, max_turns, model_id=resolved,
        )
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
        model: str | None = None,
    ) -> Iterator[str]:
        """Stream-json variant of ask_local: yields assistant text chunks
        as `claude -p` produces them, instead of buffering the entire
        response.

        Uses `--output-format stream-json` which emits one JSON object
        per line on stdout. Each object has a `type` field; we forward
        the text contents of `assistant` messages and ignore everything
        else (tool calls, system messages).

        v11.0.0a5: also captures per-message + final `result` usage
        blocks into a `StreamUsage` exposed on the returned iterator
        as `.usage`. The SSE `usage` event emitter reads this after
        iteration completes; backends that don't report a usage block
        (older claude versions) leave `has_real_usage = False` and the
        emitter falls back to chunk-count approximation.

        Failure modes match ask_local:
          - timeout → BackendError(code='timeout') after killing the subprocess
          - non-zero exit → BackendError(code='exit_nonzero')
          - malformed line → BackendError(code='parse_failure')

        The iterator is exhausted when stdout closes; callers MUST drain
        it (or use a context that does) so the subprocess is reaped.
        """
        cmd = [self.cfg.binary, "-p"]
        resolved = self._resolve_model(model)
        if resolved:
            cmd += ["--model", resolved]
        cmd += [
            "--permission-mode", "bypassPermissions",
            "--max-turns", str(max_turns),
            "--output-format", "stream-json",
            "--verbose",  # stream-json requires --verbose in current claude-code
            prompt,
        ]
        usage = StreamUsage()
        proc = subprocess.Popen(
            cmd, cwd=str(cwd),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,  # line-buffered
        )
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
                            f"timeout: claude -p exceeded {self.cfg.timeout_local}s",
                            code="timeout",
                        )
                    stripped = line.strip()
                    if not stripped:
                        continue
                    yield from self._extract_assistant_text(stripped, usage=usage)
            finally:
                # Always drain stderr + reap the subprocess so we don't
                # leak zombies even when the caller stops iterating early.
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
                        f"claude -p exit {rc}: {stderr_tail or '(no stderr)'}",
                        code="exit_nonzero",
                    )

        return _StreamWithUsage(_gen(), usage)

    @staticmethod
    def _extract_assistant_text(
        line: str, *, usage: StreamUsage | None = None,
    ) -> Iterator[str]:
        """Parse one stream-json line and yield text deltas if it is an
        assistant message. Anything else (system, tool_use, result) is
        silently skipped for text purposes — those don't carry
        user-facing tokens — but `result` lines DO carry the
        authoritative final usage block, which we feed into the
        passed-in `StreamUsage` (v11.0.0a5).

        v16.0.0a6: ``tool_use`` blocks emit child spans tagged with
        the active dispatch's ``span_id`` / ``trace_id`` (via
        :func:`harbormaster.fleetq.current_span_id`) so the
        dispatcher trace surface can show parent/child waterfall
        rows. ``tool_result`` blocks close the matching child span.
        Failures inside the instrumentation are silently swallowed
        — tracing is best-effort, never blocks the user-facing text.

        Tolerates malformed lines (raises BackendError only when the
        upstream contract is clearly broken).
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
        if usage is not None:
            usage.merge_message_usage(msg)
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
            block_type = block.get("type")
            if block_type == "tool_use":
                # v16.0.0a6: best-effort child-span emission.
                _maybe_emit_tool_use_span(block)
                continue
            if block_type == "tool_result":
                _maybe_close_tool_result_span(block)
                continue
            if block_type != "text":
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
        model: str | None = None,
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
        resolved = self._resolve_model(model)
        model_part = f"--model {shlex.quote(resolved)} " if resolved else ""
        remote_cmd = (
            f"cd {qcwd} && {qbin} -p "
            f"{model_part}"
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
                            f"timeout: ssh+claude exceeded {total_timeout}s",
                            code="timeout",
                        )
                    stripped = line.strip()
                    if not stripped:
                        continue
                    # Tolerate non-JSON lines (login banner / shell
                    # prompt / ssh status messages). Only assistant
                    # text deltas reach the caller; usage blocks (v11)
                    # land in `usage` via _extract_assistant_text.
                    try:
                        yield from self._extract_assistant_text(
                            stripped, usage=usage,
                        )
                    except BackendError as e:
                        if e.code == "parse_failure":
                            continue
                        raise
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
                        f"remote claude -p exit {rc}: {stderr_tail or '(no stderr)'}",
                        code="exit_nonzero",
                    )

        return _StreamWithUsage(_gen(), usage)

    # ----- private helpers --------------------------------------------------

    def _build_remote_command(
        self, remote_cwd: str, prompt: str, max_turns: int,
        *, model_id: str | None = None,
    ) -> str:
        """Compose the bash command sent to the remote host. All user-supplied
        values pass through shlex.quote before assembly.

        v21.0.0a10: when `model_id` is non-None it is injected as
        `--model <id>` immediately after `-p`. The caller is responsible
        for resolving aliases / whitelist enforcement via
        `_resolve_model` before passing the value in.
        """
        qcwd = shlex.quote(remote_cwd)
        qprompt = shlex.quote(prompt)
        qbin = shlex.quote(self.cfg.binary)
        qmaxturns = shlex.quote(str(max_turns))
        model_part = f"--model {shlex.quote(model_id)} " if model_id else ""
        return (
            f"cd {qcwd} && {qbin} -p "
            f"{model_part}"
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

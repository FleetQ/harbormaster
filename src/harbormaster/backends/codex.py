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

# v17.0.0a2: per-process registry mapping a codex `call_id` (or
# `tool_use.id`) to the running span we opened for it. Mirrors the
# claude.py pattern (see `_TOOL_USE_SPANS` there). Best-effort: if a
# tool_use lands without a matching result (cancel / parse miss),
# the entry just stays pinned until the process restarts.
_TOOL_USE_SPANS: dict[str, object] = {}


def _maybe_emit_tool_use_span(block: dict[str, object]) -> None:
    """v17.0.0a2: open a child span for a codex tool-call event, if a
    parent dispatch is currently active. Failures are swallowed.

    Mirrors `harbormaster.backends.claude._maybe_emit_tool_use_span`
    so the dispatcher trace surface gets the same parent/child shape
    regardless of which backend served the dispatch. The span tool
    name is prefixed ``codex.tool:`` so operators can tell the two
    backends apart in the waterfall view.

    Codex's CLI doesn't have a single canonical tool-call shape —
    `--json` mode emits OpenAI-style ``{"type": "function_call",
    "name": ..., "call_id": ...}`` while some wrappers emit Claude-
    style ``{"type": "tool_use", "id": ..., "name": ...}``. We
    accept both: ``id`` is taken from ``call_id`` first, falling
    back to ``id``; the tool name is taken from ``name``.
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
    # Codex `--json` shape uses `call_id`; some wrappers use `id`.
    use_id = block.get("call_id") or block.get("id")
    name = block.get("name")
    if not isinstance(use_id, str) or not isinstance(name, str):
        return
    try:
        span = get_dispatcher_stats().record_start(
            tool=f"codex.tool:{name}",
            parent_span_id=parent,
            trace_id=current_trace_id(),
        )
    except Exception:  # noqa: BLE001
        return
    _TOOL_USE_SPANS[use_id] = span


def _maybe_close_tool_result_span(block: dict[str, object]) -> None:
    """v17.0.0a2: close the child span previously opened for the
    matching tool-call id. Mirrors the claude.py helper.

    Codex `--json` mode emits ``{"type": "function_call_output",
    "call_id": ...}``; Claude-style wrappers emit
    ``{"type": "tool_result", "tool_use_id": ...}``. We accept
    both correlations.
    """
    try:
        from harbormaster.fleetq import get_dispatcher_stats
    except Exception:  # noqa: BLE001
        return
    use_id = block.get("call_id") or block.get("tool_use_id")
    if not isinstance(use_id, str):
        return
    span = _TOOL_USE_SPANS.pop(use_id, None)
    if span is None:
        return
    # Codex function_call_output has no boolean error flag — instead
    # the output text may carry `is_error: true` or an error envelope.
    # Honor `is_error` if present; otherwise default to ok=True.
    is_error = bool(block.get("is_error"))
    try:
        get_dispatcher_stats().record_end(span, ok=not is_error)  # type: ignore[arg-type]
    except Exception:  # noqa: BLE001
        return


def _maybe_observe_codex_line(line: str) -> None:
    """v17.0.0a2: best-effort line-level instrumentation hook.

    Called for every codex stdout line during streaming. If the line
    parses as JSON and matches a known tool-call / tool-result shape,
    open or close the matching child span via the helpers above.

    Recognised event shapes (any one of):
      * ``{"type": "tool_use", "id": ..., "name": ...}`` — Claude-style.
      * ``{"type": "function_call", "call_id": ..., "name": ...}`` —
        codex `--json` mode; OpenAI Responses API shape.
      * ``{"type": "tool_result", "tool_use_id": ..., "is_error": ...}``
        — Claude-style result.
      * ``{"type": "function_call_output", "call_id": ...}`` — codex
        `--json` mode; OpenAI Responses API shape.

    Anything else (including non-JSON lines, JSON without a `type`
    key, or `type` values we don't recognise) is a silent no-op.
    Failures inside the helpers are already swallowed.
    """
    stripped = line.strip()
    if not stripped or stripped[0] not in "{":
        return
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        return
    if not isinstance(parsed, dict):
        return
    block_type = parsed.get("type")
    if block_type in ("tool_use", "function_call"):
        _maybe_emit_tool_use_span(parsed)
    elif block_type in ("tool_result", "function_call_output"):
        _maybe_close_tool_result_span(parsed)


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

    def _resolve_model(self, model: str | None) -> str | None:
        """v21.0.0a10: same shape as ClaudeBackend._resolve_model.

        Codex's `model_aliases` default to the claude shorthand
        (haiku/sonnet/opus) — operators wiring codex up should override
        the aliases in TOML to map to gpt-5 / o1 / etc. The whitelist
        + None-passthrough behaviour is identical.
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
        resolved = self._resolve_model(model)
        model_args = ["--model", resolved] if resolved else []
        cmd = [self.cfg.binary, *self.cfg.extra_args, *model_args, prompt]
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
            # v21.0.7: include elapsed + stderr_tail so the agent /
            # operator can see what was happening when codex got killed.
            elapsed = time.monotonic() - start
            stderr_tail = ""
            if e.stderr:
                raw = e.stderr if isinstance(e.stderr, str) else e.stderr.decode(
                    "utf-8", errors="replace",
                )
                stderr_tail = raw[-300:]
            tail_hint = f" stderr_tail={stderr_tail!r}" if stderr_tail else ""
            raise BackendError(
                f"timeout: {self.cfg.binary} exceeded {self.cfg.timeout_local}s "
                f"(elapsed={elapsed:.1f}s){tail_hint}",
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
        model: str | None = None,
    ) -> BackendResult:
        resolved = self._resolve_model(model)
        remote_cmd = self._build_remote_command(remote_cwd, prompt, model_id=resolved)
        start = time.monotonic()
        try:
            proc = run_ssh(
                host,
                remote_cmd,
                total_timeout=total_timeout,
                connect_timeout=connect_timeout,
            )
        except SshTimeoutError as e:
            # v21.0.7: distinguish "ssh connect never succeeded" from
            # "remote codex hung" via elapsed vs configured timeouts.
            elapsed = time.monotonic() - start
            raise BackendError(
                f"{e} (elapsed={elapsed:.1f}s, "
                f"connect_timeout={connect_timeout}s, "
                f"total_timeout={total_timeout}s)",
                code="timeout",
            ) from e

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

    def _build_remote_command(
        self, remote_cwd: str, prompt: str,
        *, model_id: str | None = None,
    ) -> str:
        """Compose the bash command sent to the remote host. All
        user-supplied values pass through `shlex.quote` before assembly.

        v21.0.0a10: when `model_id` is non-None it is appended as
        `--model <id>` after `extra_args`."""
        qcwd = shlex.quote(remote_cwd)
        qprompt = shlex.quote(prompt)
        qbin = shlex.quote(self.cfg.binary)
        qextra = " ".join(shlex.quote(a) for a in self.cfg.extra_args)
        space = " " if qextra else ""
        model_part = f" --model {shlex.quote(model_id)}" if model_id else ""
        return f"cd {qcwd} && {qbin}{space}{qextra}{model_part} -- {qprompt}"

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
        model: str | None = None,
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
        resolved = self._resolve_model(model)
        model_args = ["--model", resolved] if resolved else []
        cmd = [self.cfg.binary, *self.cfg.extra_args, *model_args, prompt]
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
                    # v17.0.0a2: best-effort tool_use child-span emit;
                    # never blocks text yield.
                    _maybe_observe_codex_line(line)
                    if self._absorb_optional_usage_line(line, usage):
                        continue
                    if self._is_tool_event_line(line):
                        # Don't surface tool_use / tool_result JSON
                        # records as visible text — they're metadata.
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
        model: str | None = None,
    ) -> Iterator[str]:
        """SSH variant of ask_local_stream — pipe codex stdout through
        ssh and yield lines as deltas as they arrive. Same usage-soft-fall
        contract as the local path.
        """
        from harbormaster.ssh import build_ssh_argv

        resolved = self._resolve_model(model)
        remote_cmd = self._build_remote_command(remote_cwd, prompt, model_id=resolved)
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
                    # v17.0.0a2: best-effort tool_use child-span emit;
                    # never blocks text yield.
                    _maybe_observe_codex_line(line)
                    if self._absorb_optional_usage_line(line, usage):
                        continue
                    if self._is_tool_event_line(line):
                        # Don't surface tool_use / tool_result JSON
                        # records as visible text — they're metadata.
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
    def _is_tool_event_line(line: str) -> bool:
        """v17.0.0a2: True if the line parses as a JSON object whose
        ``type`` is one of the recognised tool-call / tool-result
        shapes consumed by `_maybe_observe_codex_line`. Used by the
        streaming path to suppress those lines from the visible
        text output (they're observability metadata, not user text).

        Tolerates malformed input — anything that isn't a clean JSON
        object with a known ``type`` is treated as text.
        """
        stripped = line.strip()
        if not stripped or stripped[0] not in "{":
            return False
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError:
            return False
        if not isinstance(parsed, dict):
            return False
        return parsed.get("type") in (
            "tool_use",
            "tool_result",
            "function_call",
            "function_call_output",
        )

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

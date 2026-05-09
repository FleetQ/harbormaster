"""Shared helpers for tool implementations (private to harbormaster.tools).

Translates between the typed Backend interface (which raises BackendError on
failure) and the MCP user-facing string contract (which returns 'Error: ...'
prefixed strings so the envelope stays consistent across tools).
"""
from __future__ import annotations

import os
import time
from collections.abc import Iterator
from pathlib import Path

from harbormaster.backends import BackendError, get_backend
from harbormaster.config import HarbormasterConfig
from harbormaster.projects import resolve_project, validate_project_name
from harbormaster.ssh import is_remote


def _dump_dir() -> Path:
    """Return the directory for truncated-output dumps.

    Uses $XDG_STATE_HOME (or ~/.local/state) by default, NOT /tmp — claude
    output may include private code, secrets, or SSH host data. Creates the
    directory mode 0o700 (owner-only) on first use.
    """
    state = os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local" / "state")
    d = Path(state) / "harbormaster" / "dumps"
    d.mkdir(parents=True, exist_ok=True, mode=0o700)
    return d


def run_backend(
    *,
    name: str,
    prompt: str,
    max_turns: int,
    host: str | None,
    config: HarbormasterConfig,
    label_prefix: str,
) -> str:
    """Dispatch a prompt to local or remote backend, return the (possibly
    truncated) result text or an 'Error: ...' string.

    No SSH glue here — that's encapsulated inside the backend. This function
    is purely orchestration: validate the project name, pick the backend,
    pick local-vs-remote, dispatch, and translate exceptions to strings at
    the MCP boundary.
    """
    try:
        validate_project_name(name)
    except ValueError as e:
        return f"Error: {e}"

    backend = get_backend(config)
    if backend is None:
        return "Error: backend 'claude' is not enabled in config"
    cap = backend.cfg.output_word_cap

    try:
        if is_remote(host):
            host_cfg = config.hosts.get(host)
            remote_htdocs = host_cfg.remote_htdocs if host_cfg else "~/htdocs"
            connect_timeout = host_cfg.connect_timeout if host_cfg else 10
            total_timeout = host_cfg.total_timeout if host_cfg else 120
            result = backend.ask_remote(
                host=host,
                remote_cwd=f"{remote_htdocs}/{name}",
                prompt=prompt,
                max_turns=max_turns,
                connect_timeout=connect_timeout,
                total_timeout=total_timeout,
            )
            label = f"{label_prefix}-{host}-{name}"
        else:
            try:
                cwd = resolve_project(name, config.projects)
            except ValueError as e:
                return f"Error: {e}"
            result = backend.ask_local(
                cwd=cwd, prompt=prompt, max_turns=max_turns
            )
            label = f"{label_prefix}-{name}"
    except BackendError as e:
        return f"Error: {e}"

    return _truncate(result.output, cap, label)


def make_local_backend_stream(
    *,
    project_name: str,
    prompt: str,
    max_turns: int,
    config: HarbormasterConfig,
) -> Iterator[str]:
    """Eagerly validate inputs and return the backend's streaming
    iterator against a local project.

    Tool-agnostic: callers (ask_project, delegate_task, future tools)
    are responsible for building the full prompt before invoking this.
    This function only worries about backend availability + project
    resolution, NOT tool-specific framing.

    Important: this function is **not** a generator function — `yield`
    appears nowhere in its body. That's deliberate: argument validation
    (project name, backend availability, project resolution) must run
    when the function is called, not lazily on the first `next()` of
    a returned generator. Lazy validation makes it impossible for the
    SSE dispatcher to distinguish "bad input → 400" from "subprocess
    died mid-stream → 502" because both errors bubble out of the same
    `next()` call site.

    Failure modes (raised eagerly — callers map to SSE error events):
      - ValueError       → invalid project name / project not found
      - BackendError     → backend disabled / streaming not supported
                           / subprocess failure (raised lazily on first
                           next() once iteration starts)
    """
    validate_project_name(project_name)
    backend = get_backend(config)
    if backend is None:
        raise BackendError(
            "backend 'claude' is not enabled in config",
            code="config_error",
        )
    if not hasattr(backend, "ask_local_stream"):
        raise BackendError(
            f"backend {backend.name!r} does not support streaming",
            code="config_error",
        )
    cwd = resolve_project(project_name, config.projects)
    return backend.ask_local_stream(
        cwd=cwd, prompt=prompt, max_turns=max_turns,
    )


def make_remote_backend_stream(
    *,
    project_name: str,
    prompt: str,
    max_turns: int,
    host: str,
    config: HarbormasterConfig,
) -> Iterator[str]:
    """SSH counterpart to make_local_backend_stream — eagerly validates and
    returns the remote streaming iterator.

    Tool-agnostic: callers build the full prompt; this function only
    handles backend lookup and host-config resolution.

    Failure modes (raised eagerly):
      - ValueError      → invalid project name
      - BackendError    → backend disabled / streaming not supported
                          / SSH or remote-process failure (raised on
                          first next() once iteration begins)
    """
    validate_project_name(project_name)
    backend = get_backend(config)
    if backend is None:
        raise BackendError(
            "backend 'claude' is not enabled in config",
            code="config_error",
        )
    if not hasattr(backend, "ask_remote_stream"):
        raise BackendError(
            f"backend {backend.name!r} does not support remote streaming",
            code="config_error",
        )
    host_cfg = config.hosts.get(host)
    remote_htdocs = host_cfg.remote_htdocs if host_cfg else "~/htdocs"
    connect_timeout = host_cfg.connect_timeout if host_cfg else 10
    total_timeout = host_cfg.total_timeout if host_cfg else 120
    return backend.ask_remote_stream(
        host=host,
        remote_cwd=f"{remote_htdocs}/{project_name}",
        prompt=prompt,
        max_turns=max_turns,
        connect_timeout=connect_timeout,
        total_timeout=total_timeout,
    )


def _truncate(text: str, word_cap: int, source_label: str) -> str:
    words = text.split()
    if len(words) <= word_cap:
        return text
    truncated = " ".join(words[:word_cap])
    try:
        dump_path = _dump_dir() / f"harbormaster-{source_label}-{int(time.time())}.md"
        dump_path.write_text(text, encoding="utf-8")
        os.chmod(dump_path, 0o600)
        return f"{truncated}\n\n[...truncated, full output: {dump_path}]"
    except OSError:
        return f"{truncated}\n\n[...truncated, dump failed]"

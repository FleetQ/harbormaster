"""Shared helpers for tool implementations (private to harbormaster.tools)."""
from __future__ import annotations

import time
from pathlib import Path

from harbormaster.backends import BackendError, ClaudeBackend
from harbormaster.config import HarbormasterConfig
from harbormaster.projects import resolve_project
from harbormaster.ssh import (
    SshTimeout,
    diagnose_ssh_failure,
    is_remote,
    run_ssh,
)

DUMP_DIR = Path("/tmp")


def _get_backend(config: HarbormasterConfig, name: str = "claude") -> ClaudeBackend | None:
    cfg = config.backends.get(name)
    if cfg is None or not cfg.enabled:
        return None
    return ClaudeBackend(cfg)


def run_backend(
    *,
    name: str,
    prompt: str,
    max_turns: int,
    host: str | None,
    config: HarbormasterConfig,
    label_prefix: str,
) -> str:
    """Dispatch a prompt to local or remote backend.

    Returns either the (possibly truncated) result text, or a string starting
    with 'Error: ...' so the MCP envelope stays consistent across tools.
    """
    backend = _get_backend(config)
    if backend is None:
        return "Error: backend 'claude' is not enabled in config"
    cap = backend.cfg.output_word_cap

    if is_remote(host):
        host_cfg = config.hosts.get(host)
        remote_htdocs = host_cfg.remote_htdocs if host_cfg else "~/htdocs"
        connect_timeout = host_cfg.connect_timeout if host_cfg else 10
        total_timeout = host_cfg.total_timeout if host_cfg else 120

        remote_cmd = backend.build_remote_command(
            remote_cwd=f"{remote_htdocs}/{name}",
            prompt=prompt,
            max_turns=max_turns,
        )
        try:
            proc = run_ssh(
                host, remote_cmd,
                total_timeout=total_timeout,
                connect_timeout=connect_timeout,
            )
        except SshTimeout as e:
            return f"Error: {e}"
        err = diagnose_ssh_failure(host, proc)
        if err:
            return f"Error: {err}"
        if proc.returncode != 0:
            stderr_tail = (proc.stderr or "")[-500:]
            return f"Error: remote backend exit {proc.returncode}: {stderr_tail}"
        try:
            result = backend.parse_remote_stdout(proc.stdout)
        except BackendError as e:
            return f"Error: {e}"
        return _truncate(result, cap, f"{label_prefix}-{host}-{name}")

    # Local
    try:
        cwd = resolve_project(name, config.projects)
    except ValueError as e:
        return f"Error: {e}"
    try:
        result = backend.ask_local(cwd=cwd, prompt=prompt, max_turns=max_turns)
    except BackendError as e:
        return f"Error: {e}"
    return _truncate(result, cap, f"{label_prefix}-{name}")


def _truncate(text: str, word_cap: int, source_label: str) -> str:
    words = text.split()
    if len(words) <= word_cap:
        return text
    truncated = " ".join(words[:word_cap])
    dump_path = DUMP_DIR / f"harbormaster-{source_label}-{int(time.time())}.md"
    try:
        dump_path.write_text(text, encoding="utf-8")
        return f"{truncated}\n\n[...truncated, full output: {dump_path}]"
    except OSError:
        return f"{truncated}\n\n[...truncated, dump failed]"

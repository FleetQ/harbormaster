"""SSH layer: command builder, runner, host discovery.

Every user-supplied value passed into a remote command MUST go through
`quote_for_remote()` before assembly. This module is the single source of truth
for what an `ssh ...` argv looks like.
"""
from __future__ import annotations

import re
import shlex
import subprocess
from pathlib import Path
from typing import TypeGuard

SSH_CONFIG_PATH = Path.home() / ".ssh" / "config"


class SshError(Exception):
    """SSH connection / auth failure (distinct from remote-command failure)."""


class SshTimeoutError(SshError):
    """SSH operation exceeded configured timeout."""


def is_remote(host: str | None) -> TypeGuard[str]:
    """A None or 'local' host means run locally; anything else is treated as SSH alias.

    Returns a TypeGuard so mypy can narrow `host` to `str` after a True check.
    """
    return bool(host) and host != "local"


def quote_for_remote(value: str) -> str:
    """Shell-quote a value for safe interpolation into a remote command string.

    Always use this before f-stringing user input into a command sent over SSH.
    """
    return shlex.quote(value)


def build_ssh_argv(
    host: str, remote_cmd: str, *, connect_timeout: int = 10
) -> list[str]:
    """Build the local argv for `ssh ... bash -lc <remote_cmd>`.

    The caller is responsible for shlex.quote-ing values *inside* remote_cmd.
    """
    return [
        "ssh",
        "-o", f"ConnectTimeout={connect_timeout}",
        "-o", "BatchMode=yes",
        host,
        "bash", "-lc", remote_cmd,
    ]


def run_ssh(
    host: str,
    remote_cmd: str,
    *,
    total_timeout: int,
    connect_timeout: int = 10,
) -> subprocess.CompletedProcess[str]:
    """Synchronously run a remote command. Raises SshTimeout on overall timeout."""
    cmd = build_ssh_argv(host, remote_cmd, connect_timeout=connect_timeout)
    try:
        return subprocess.run(
            cmd, capture_output=True, text=True, timeout=total_timeout
        )
    except subprocess.TimeoutExpired as e:
        raise SshTimeoutError(f"SSH to '{host}' exceeded {total_timeout}s") from e


def diagnose_ssh_failure(
    host: str, proc: subprocess.CompletedProcess[str]
) -> str | None:
    """Return human-readable error if SSH itself failed; None if SSH succeeded.

    Distinguishes SSH-layer failures (connection refused, auth, host key) from
    remote-command non-zero exits (which the caller should map to BackendError).
    """
    if proc.returncode == 0:
        return None
    stderr = (proc.stderr or "").strip()
    indicators = (
        "Could not resolve hostname",
        "Connection refused",
        "Connection timed out",
        "Permission denied",
        "Host key verification failed",
        "ssh: connect to host",
        "kex_exchange_identification",
    )
    if any(ind in stderr for ind in indicators):
        last_line = stderr.splitlines()[-1] if stderr else "unknown error"
        msg = f"SSH to '{host}' failed: {last_line}"
        if "Host key verification failed" in stderr:
            msg += (
                " (hint: BatchMode=yes blocks the interactive prompt; "
                "ssh manually once to accept the host key, then retry)"
            )
        elif "Permission denied" in stderr:
            msg += (
                " (hint: BatchMode=yes blocks password prompts; "
                "set up an SSH key for this host)"
            )
        return msg
    return None


def list_ssh_hosts() -> list[str]:
    """Parse ~/.ssh/config and return non-wildcard Host aliases.

    Returns [] if the file is missing or unreadable. Wildcards ('*', '?') skipped.
    """
    if not SSH_CONFIG_PATH.is_file():
        return []
    try:
        text = SSH_CONFIG_PATH.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    hosts: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        m = re.match(r"(?i)^Host\s+(.+)$", stripped)
        if not m:
            continue
        for alias in m.group(1).split():
            if "*" in alias or "?" in alias:
                continue
            if alias not in hosts:
                hosts.append(alias)
    return hosts

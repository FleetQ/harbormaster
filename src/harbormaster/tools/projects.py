"""list_projects + project_status MCP tools."""
from __future__ import annotations

import subprocess

from mcp.server.fastmcp import FastMCP

from harbormaster.config import HarbormasterConfig
from harbormaster.projects import discover_projects, resolve_project, validate_project_name
from harbormaster.ssh import (
    SshTimeoutError,
    diagnose_ssh_failure,
    is_remote,
    quote_for_remote,
    run_ssh,
)


def register(mcp: FastMCP, config: HarbormasterConfig) -> None:
    @mcp.tool()
    def list_projects(host: str | None = None) -> list[dict[str, object]] | list[str]:
        """List projects from configured globs (local) or remote SSH host.

        Local: rich list of dicts (name, path, last_commit, has_serena,
        has_claude_md, brief), sorted by last commit date desc.
        Remote: flat list of directory names from `ls -1 <remote_htdocs>`.
        """
        if is_remote(host):
            host_cfg = config.hosts.get(host)
            remote_htdocs = host_cfg.remote_htdocs if host_cfg else "~/htdocs"
            connect_timeout = host_cfg.connect_timeout if host_cfg else 10
            remote_cmd = f"ls -1 {quote_for_remote(remote_htdocs)}"
            try:
                proc = run_ssh(
                    host, remote_cmd,
                    total_timeout=connect_timeout + 10,
                    connect_timeout=connect_timeout,
                )
            except SshTimeoutError as e:
                return [f"Error: {e}"]
            err = diagnose_ssh_failure(host, proc)
            if err:
                return [f"Error: {err}"]
            if proc.returncode != 0:
                stderr_tail = (proc.stderr or "").strip()[-200:]
                return [f"Error: remote ls exit {proc.returncode}: {stderr_tail}"]
            return [line.strip() for line in proc.stdout.splitlines() if line.strip()]

        return [
            p.as_dict() for p in discover_projects(
                config.projects, ignore_patterns=config.ignore.patterns,
            )
        ]

    @mcp.tool()
    def project_status(name: str, host: str | None = None) -> str:
        """Fast read-only status snapshot of a project.

        Includes last 5 commits, current branch, uncommitted file count,
        Serena memory file names, and tail of the most recent storage/logs/*.log.
        Does NOT invoke Claude.
        """
        if is_remote(host):
            return _remote_status(host, name, config)
        return _local_status(name, config)


def _local_status(name: str, config: HarbormasterConfig) -> str:
    try:
        p = resolve_project(
            name, config.projects, ignore_patterns=config.ignore.patterns,
        )
    except ValueError as e:
        return f"Error: {e}"

    lines = [f"## {name} — current state", f"Path: `{p}`", ""]

    log = subprocess.run(
        ["git", "-C", str(p), "log", "-5", "--format=- %h %s (%cr)"],
        capture_output=True, text=True, timeout=5,
    )
    if log.returncode == 0 and log.stdout.strip():
        lines.append("**Recent commits:**")
        lines.append(log.stdout.rstrip())
        lines.append("")

    branch = subprocess.run(
        ["git", "-C", str(p), "rev-parse", "--abbrev-ref", "HEAD"],
        capture_output=True, text=True, timeout=5,
    )
    if branch.returncode == 0:
        lines.append(f"**Branch:** `{branch.stdout.strip()}`")

    status = subprocess.run(
        ["git", "-C", str(p), "status", "--porcelain"],
        capture_output=True, text=True, timeout=5,
    )
    if status.returncode == 0:
        n = len([line for line in status.stdout.splitlines() if line.strip()])
        lines.append(f"**Uncommitted:** {n} file(s)")

    lines.append("")

    serena_dir = p / ".serena" / "memories"
    if serena_dir.is_dir():
        memories = sorted(f.name for f in serena_dir.iterdir() if f.is_file())
        if memories:
            lines.append(f"**Serena memories ({len(memories)}):**")
            for m in memories[:30]:
                lines.append(f"- {m}")
            if len(memories) > 30:
                lines.append(f"- ...and {len(memories) - 30} more")
            lines.append("")

    log_dir = p / "storage" / "logs"
    if log_dir.is_dir():
        log_files = sorted(log_dir.glob("*.log"), key=lambda f: f.stat().st_mtime, reverse=True)
        if log_files:
            recent = log_files[0]
            try:
                tail = subprocess.run(
                    ["tail", "-20", str(recent)],
                    capture_output=True, text=True, timeout=5,
                )
                if tail.returncode == 0 and tail.stdout.strip():
                    lines.append(f"**Last 20 lines of `{recent.name}`:**")
                    lines.append("```")
                    lines.append(tail.stdout.rstrip())
                    lines.append("```")
            except subprocess.TimeoutExpired:
                pass

    return "\n".join(lines)


def _remote_status(host: str, name: str, config: HarbormasterConfig) -> str:
    try:
        validate_project_name(name)
    except ValueError as e:
        return f"Error: {e}"

    host_cfg = config.hosts.get(host)
    remote_htdocs = host_cfg.remote_htdocs if host_cfg else "~/htdocs"
    connect_timeout = host_cfg.connect_timeout if host_cfg else 10

    qname = quote_for_remote(name)
    qpath = quote_for_remote(f"{remote_htdocs}/{name}")
    qhost = quote_for_remote(host)
    # printf with %s is the safe way to print already-shell-quoted untrusted values.
    script = (
        f"set -e; cd {qpath} 2>/dev/null || {{ echo __NOPROJECT__; exit 2; }}; "
        f"printf '## %s — current state (remote: %s)\\n' {qname} {qhost}; "
        f"printf 'Path: %s\\n\\n' {qpath}; "
        "echo '**Recent commits:**'; "
        "git log -5 --format='- %h %s (%cr)' 2>/dev/null || echo '(no git)'; echo; "
        "echo -n '**Branch:** '; git rev-parse --abbrev-ref HEAD 2>/dev/null || echo '(none)'; "
        "echo -n '**Uncommitted:** '; git status --porcelain 2>/dev/null | wc -l | tr -d ' '; "
        "echo ' file(s)'; echo; "
        "if [ -d .serena/memories ]; then "
        "  echo '**Serena memories:**'; ls -1 .serena/memories | head -30 | sed 's/^/- /'; "
        "fi"
    )
    try:
        proc = run_ssh(
            host, script,
            total_timeout=connect_timeout + 15,
            connect_timeout=connect_timeout,
        )
    except SshTimeoutError as e:
        return f"Error: {e}"
    err = diagnose_ssh_failure(host, proc)
    if err:
        return f"Error: {err}"
    if "__NOPROJECT__" in proc.stdout:
        return f"Error: project '{name}' not found at {remote_htdocs}/{name} on '{host}'"
    if proc.returncode != 0:
        stderr_tail = (proc.stderr or "").strip()[-200:]
        return f"Error: remote status exit {proc.returncode}: {stderr_tail}"
    return proc.stdout.rstrip()

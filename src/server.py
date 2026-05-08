#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["mcp>=1.2.0"]
# ///
"""Project Router MCP — route questions and tasks to per-project Claude Code subagents.

Lives at: ~/htdocs/project-router-mcp/src/server.py
Registered in: ~/.claude/settings.json mcpServers.project-router

Tools:
  list_projects(host=None)                              -> list[ProjectInfo] | list[str]
  project_status(name, host=None)                       -> str (markdown)
  ask_project(name, question, max_turns=5, host=None)   -> str (<800 words)
  delegate_task(name, task, deliverable,
                allow_writes=False, host=None)          -> str | error (fail-closed for writes in v1)
  list_hosts()                                          -> list[str]
"""

from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from mcp.server.fastmcp import FastMCP

HTDOCS = Path.home() / "htdocs"
SUBPROCESS_TIMEOUT = 60
REMOTE_SUBPROCESS_TIMEOUT = 90  # SSH handshake + remote claude -p
SSH_CONNECT_TIMEOUT = 10
MAX_RESPONSE_WORDS = 800
DUMP_DIR = Path("/tmp")
SSH_CONFIG_PATH = Path.home() / ".ssh" / "config"
REMOTE_HTDOCS = os.environ.get("ROUTER_REMOTE_HTDOCS", "~/htdocs")

mcp = FastMCP("project-router")


@dataclass
class ProjectInfo:
    name: str
    path: str
    last_commit: dict | None
    has_serena: bool
    has_claude_md: bool
    brief: str


def _is_remote(host: str | None) -> bool:
    return bool(host) and host != "local"


def _ssh_base(host: str) -> list[str]:
    return [
        "ssh",
        "-o", f"ConnectTimeout={SSH_CONNECT_TIMEOUT}",
        "-o", "BatchMode=yes",
        host,
    ]


def _run_ssh(host: str, remote_cmd: str, timeout: int) -> subprocess.CompletedProcess:
    """Run a shell command on `host` via `ssh ... bash -lc <cmd>`. Caller passes
    a fully-quoted remote_cmd; we wrap it once more for `bash -lc`.
    """
    cmd = _ssh_base(host) + ["bash", "-lc", remote_cmd]
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def _ssh_error_message(host: str, proc: subprocess.CompletedProcess) -> str | None:
    """Detect SSH-layer failures (vs remote command failures). Returns a message
    string if SSH itself failed, else None.
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
        return f"SSH to '{host}' failed: {stderr.splitlines()[-1] if stderr else 'unknown error'}"
    return None


def _is_project(p: Path) -> bool:
    return p.is_dir() and (
        (p / ".git").is_dir() or (p / "CLAUDE.md").is_file()
    )


def _git_last_commit(path: Path) -> dict | None:
    try:
        out = subprocess.run(
            ["git", "-C", str(path), "log", "-1", "--format=%h%x09%s%x09%cI"],
            capture_output=True, text=True, timeout=5,
        )
        if out.returncode != 0:
            return None
        h, subject, date = out.stdout.strip().split("\t", 2)
        return {"hash": h, "subject": subject, "date": date}
    except (subprocess.TimeoutExpired, ValueError, FileNotFoundError):
        return None


def _project_brief(path: Path) -> str:
    for fname in ("CLAUDE.md", "README.md", "README.txt"):
        f = path / fname
        if f.is_file():
            try:
                text = f.read_text(encoding="utf-8", errors="replace")
                # Strip frontmatter and headers, take first ~200 chars of body
                body = re.sub(r"^---.*?---\s*", "", text, flags=re.DOTALL)
                body = re.sub(r"^#.*?$", "", body, flags=re.MULTILINE).strip()
                return body[:200].replace("\n", " ").strip()
            except OSError:
                pass
    return ""


def _resolve_project(name: str) -> Path:
    p = (HTDOCS / name).resolve()
    if HTDOCS.resolve() not in p.parents or not _is_project(p):
        available = sorted(c.name for c in HTDOCS.iterdir() if _is_project(c))
        raise ValueError(f"project '{name}' not found. Available: {', '.join(available[:20])}")
    return p


def _truncate_response(text: str, source_label: str) -> str:
    words = text.split()
    if len(words) <= MAX_RESPONSE_WORDS:
        return text
    truncated = " ".join(words[:MAX_RESPONSE_WORDS])
    dump_path = DUMP_DIR / f"router-{source_label}-{int(time.time())}.md"
    try:
        dump_path.write_text(text, encoding="utf-8")
        return f"{truncated}\n\n[...truncated, full output: {dump_path}]"
    except OSError:
        return f"{truncated}\n\n[...truncated, dump failed]"


@mcp.tool()
def list_projects(host: str | None = None) -> list[dict] | list[str]:
    """List all projects under ~/htdocs/ that have a .git/ or CLAUDE.md.

    Local: returns name, path, last commit, capability flags, and a short brief.
    Remote (host set): returns a flat list of directory names from
    `ls -1 <REMOTE_HTDOCS>` over SSH.
    """
    if _is_remote(host):
        remote_cmd = f"ls -1 {shlex.quote(REMOTE_HTDOCS)}"
        try:
            proc = _run_ssh(host, remote_cmd, timeout=SSH_CONNECT_TIMEOUT + 10)
        except subprocess.TimeoutExpired:
            return [f"Error: SSH to '{host}' timed out"]
        ssh_err = _ssh_error_message(host, proc)
        if ssh_err:
            return [f"Error: {ssh_err}"]
        if proc.returncode != 0:
            stderr_tail = (proc.stderr or "").strip()[-200:]
            return [f"Error: remote ls exit {proc.returncode}: {stderr_tail}"]
        names = [line.strip() for line in proc.stdout.splitlines() if line.strip()]
        return names

    if not HTDOCS.is_dir():
        return []

    projects: list[ProjectInfo] = []
    for child in sorted(HTDOCS.iterdir()):
        if not _is_project(child):
            continue
        projects.append(
            ProjectInfo(
                name=child.name,
                path=str(child),
                last_commit=_git_last_commit(child),
                has_serena=(child / ".serena").is_dir(),
                has_claude_md=(child / "CLAUDE.md").is_file(),
                brief=_project_brief(child),
            )
        )

    projects.sort(
        key=lambda p: p.last_commit["date"] if p.last_commit else "",
        reverse=True,
    )
    return [p.__dict__ for p in projects]


def _remote_project_status(host: str, name: str) -> str:
    """Run a project_status equivalent on a remote host. Best-effort: collects
    git log/branch/status from the remote project dir.
    """
    remote_path = f"{REMOTE_HTDOCS}/{name}"
    # Compose a single remote shell that prints labeled blocks. shlex.quote on
    # name only — REMOTE_HTDOCS is from env (trusted).
    qname = shlex.quote(name)
    qpath = shlex.quote(remote_path)
    script = (
        f"set -e; cd {qpath} 2>/dev/null || {{ echo __NOPROJECT__; exit 2; }}; "
        f"echo '## {qname} — current state (remote: {shlex.quote(host)})'; "
        f"echo \"Path: \\`{remote_path}\\`\"; echo; "
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
        proc = _run_ssh(host, script, timeout=SSH_CONNECT_TIMEOUT + 15)
    except subprocess.TimeoutExpired:
        return f"Error: SSH to '{host}' timed out"
    ssh_err = _ssh_error_message(host, proc)
    if ssh_err:
        return f"Error: {ssh_err}"
    if "__NOPROJECT__" in proc.stdout:
        return f"Error: project '{name}' not found at {remote_path} on '{host}'"
    if proc.returncode != 0:
        stderr_tail = (proc.stderr or "").strip()[-200:]
        return f"Error: remote status exit {proc.returncode}: {stderr_tail}"
    return proc.stdout.rstrip()


@mcp.tool()
def project_status(name: str, host: str | None = None) -> str:
    """Return a fast read-only status snapshot of a project.

    Includes last 5 commits, current branch, ahead/behind, Serena memory file names,
    uncommitted file count, and last log lines. Does not invoke Claude.

    When `host` is set, runs the equivalent over SSH against
    `<ROUTER_REMOTE_HTDOCS or ~/htdocs>/<name>` on the remote host.
    """
    if _is_remote(host):
        return _remote_project_status(host, name)

    p = _resolve_project(name)
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
        n = len([l for l in status.stdout.splitlines() if l.strip()])
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


def _run_claude_p(cwd: Path, prompt: str, max_turns: int) -> str:
    """Spawn `claude -p` headless in cwd, return result text or raise."""
    cmd = [
        "claude", "-p",
        "--permission-mode", "bypassPermissions",
        "--max-turns", str(max_turns),
        "--output-format", "json",
        prompt,
    ]
    try:
        proc = subprocess.run(
            cmd, cwd=str(cwd), capture_output=True, text=True,
            timeout=SUBPROCESS_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"timeout: claude -p exceeded {SUBPROCESS_TIMEOUT}s")

    if proc.returncode != 0:
        stderr_tail = proc.stderr[-500:] if proc.stderr else "(no stderr)"
        raise RuntimeError(f"claude -p exit {proc.returncode}: {stderr_tail}")

    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError:
        raise RuntimeError(f"claude -p returned non-JSON: {proc.stdout[:300]}")

    result = payload.get("result") or payload.get("response") or ""
    if not result:
        raise RuntimeError(f"claude -p returned empty result. Payload keys: {list(payload.keys())}")
    return result


def _run_claude_p_remote(host: str, name: str, prompt: str, max_turns: int) -> str:
    """Spawn `claude -p` on a remote host inside <REMOTE_HTDOCS>/<name>.
    All interpolated values are shlex.quoted before assembly.
    """
    remote_path = f"{REMOTE_HTDOCS}/{name}"
    qpath = shlex.quote(remote_path)
    qprompt = shlex.quote(prompt)
    qmaxturns = shlex.quote(str(max_turns))
    # bash -lc target: cd then run claude -p with JSON output
    remote_cmd = (
        f"cd {qpath} && claude -p "
        f"--permission-mode bypassPermissions "
        f"--max-turns {qmaxturns} "
        f"--output-format json "
        f"-- {qprompt}"
    )
    try:
        proc = _run_ssh(host, remote_cmd, timeout=REMOTE_SUBPROCESS_TIMEOUT)
    except subprocess.TimeoutExpired:
        raise RuntimeError(
            f"timeout: ssh+claude -p on '{host}' exceeded {REMOTE_SUBPROCESS_TIMEOUT}s"
        )

    ssh_err = _ssh_error_message(host, proc)
    if ssh_err:
        raise RuntimeError(ssh_err)

    if proc.returncode != 0:
        stderr_tail = proc.stderr[-500:] if proc.stderr else "(no stderr)"
        raise RuntimeError(
            f"remote claude -p exit {proc.returncode} on '{host}': {stderr_tail}"
        )

    # Remote stdout may have benign login banner lines from `bash -l`. Find the
    # JSON payload by looking for the first '{' that parses cleanly.
    stdout = proc.stdout or ""
    payload = None
    candidate = stdout.strip()
    try:
        payload = json.loads(candidate)
    except json.JSONDecodeError:
        idx = stdout.find("{")
        while idx != -1:
            try:
                payload = json.loads(stdout[idx:])
                break
            except json.JSONDecodeError:
                idx = stdout.find("{", idx + 1)
    if payload is None:
        raise RuntimeError(f"remote claude -p returned non-JSON: {stdout[:300]}")

    result = payload.get("result") or payload.get("response") or ""
    if not result:
        raise RuntimeError(
            f"remote claude -p returned empty result. Payload keys: {list(payload.keys())}"
        )
    return result


@mcp.tool()
def ask_project(
    name: str, question: str, max_turns: int = 5, host: str | None = None
) -> str:
    """Ask a question of a project's Claude Code subagent.

    Spawns `claude -p` in the project's directory, where its CLAUDE.md and
    Serena memories are auto-loaded. Returns a markdown summary capped at
    ~800 words; full output dumped to /tmp if truncated.

    When `host` is set (and != "local"), runs `claude -p` on that SSH host
    inside `<ROUTER_REMOTE_HTDOCS or ~/htdocs>/<name>`. The remote host must
    have `claude` installed and authenticated (separate Anthropic seat).
    """
    full_prompt = (
        f"{question}\n\n"
        "Return a concise markdown summary under 500 words. "
        "Focus on the answer; skip unnecessary preamble."
    )
    if _is_remote(host):
        try:
            result = _run_claude_p_remote(host, name, full_prompt, max_turns)
        except RuntimeError as e:
            return f"Error: {e}"
        return _truncate_response(result, f"ask-{host}-{name}")

    p = _resolve_project(name)
    try:
        result = _run_claude_p(p, full_prompt, max_turns)
    except RuntimeError as e:
        return f"Error: {e}"
    return _truncate_response(result, f"ask-{name}")


@mcp.tool()
def delegate_task(
    name: str,
    task: str,
    deliverable: str,
    allow_writes: bool = False,
    host: str | None = None,
) -> str:
    """Delegate a task to a project's Claude Code subagent.

    v1 fails closed when allow_writes=True — call ask_project instead.
    Same fail-closed policy applies to remote runs (host set).
    """
    if allow_writes:
        return (
            "Error: delegate_task with allow_writes=True is disabled in v1. "
            "Use ask_project for read-only questions, or run the task manually "
            "in the project's directory until v2 adds an approval gate."
        )

    full_prompt = (
        f"Task: {task}\n\n"
        f"Deliverable: {deliverable}\n\n"
        "Read-only mode. Do NOT edit files. "
        "Report what you would do and which files you would touch. "
        "Return markdown under 500 words."
    )

    if _is_remote(host):
        try:
            result = _run_claude_p_remote(host, name, full_prompt, max_turns=10)
        except RuntimeError as e:
            return f"Error: {e}"
        return _truncate_response(result, f"delegate-{host}-{name}")

    p = _resolve_project(name)
    try:
        result = _run_claude_p(p, full_prompt, max_turns=10)
    except RuntimeError as e:
        return f"Error: {e}"
    return _truncate_response(result, f"delegate-{name}")


@mcp.tool()
def list_hosts() -> list[str]:
    """List Host entries from ~/.ssh/config (best-effort).

    Returns a flat list of host aliases. Wildcard hosts (containing '*' or '?')
    are skipped. Returns [] if the file is missing or unreadable.
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
        # Match `Host foo bar baz` (case-insensitive keyword)
        m = re.match(r"(?i)^Host\s+(.+)$", stripped)
        if not m:
            continue
        for alias in m.group(1).split():
            if "*" in alias or "?" in alias:
                continue
            if alias not in hosts:
                hosts.append(alias)
    return hosts


if __name__ == "__main__":
    mcp.run()

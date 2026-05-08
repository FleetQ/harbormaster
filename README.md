# project-router-mcp

Local MCP server that routes questions and tasks to per-project Claude Code subagents under `~/htdocs/` — locally on Jarvis or remotely on any SSH host.

## Why

You work across many projects, each with its own `CLAUDE.md` and Serena memories. Switching cwd loses context. This router lets the **main** Claude Code session ask any project a question without changing directory — the project's subagent loads its own memory, answers, and returns a summary.

Inspired by Google's A2A protocol pattern, but local-first and built on the tools you already have (Claude Code subagents + Serena memories). Optional SSH fan-out lets you target the same tools at remote VPS hosts.

## Tools

| Tool | Purpose | Cost |
|---|---|---|
| `list_projects(host=None)` | Enumerate `~/htdocs/*` projects with metadata. With `host`, returns remote dir listing (flat strings). | ~50ms local / ~1s remote |
| `project_status(name, host=None)` | Git log, Serena memory headers, recent log tails | ~200ms local / ~2s remote |
| `ask_project(name, question, max_turns=5, host=None)` | Spawn `claude -p` in project cwd, return ≤800 word summary | ~30s local / up to 90s remote |
| `delegate_task(name, task, deliverable, allow_writes=False, host=None)` | Read-only delegation; v1 fails closed for writes | ~60s local / up to 90s remote |
| `list_hosts()` | Read `~/.ssh/config`, return Host aliases (wildcards skipped) | ~5ms |

## Install

1. Ensure `uv` is installed: `brew install uv`
2. Add to `~/.claude/settings.json`:

   ```json
   {
     "mcpServers": {
       "project-router": {
         "command": "uv",
         "args": ["run", "/Users/katsarov/htdocs/project-router-mcp/src/server.py"],
         "env": {}
       }
     }
   }
   ```

3. Restart Claude Code. Tools appear as `mcp__project-router__list_projects`, etc.

## Usage

In any Claude Code session, regardless of cwd:

```
> Какво е състоянието на pinporn проекта?
[main agent calls project-router__project_status("pinporn")]
[returns markdown summary in <1s]

> Има ли логнати грешки в pinporn cron-а днес?
[main agent calls project-router__ask_project("pinporn", "...")]
[claude -p subprocess loads pinporn Serena memories, answers, returns ≤800 words]
```

## Remote hosts

Every project-targeting tool now accepts an optional `host` parameter. When omitted (or set to `"local"`), behavior is unchanged — `claude -p` runs locally in `~/htdocs/<name>`. When set to an SSH alias, the equivalent command runs on that host:

```
> ask_project(name="pricex", question="quick health check?", host="friday")
[ssh friday bash -lc 'cd ~/htdocs/pricex && claude -p ...']
[returns summary from Friday's claude subagent]
```

How it works:

- Transport: `ssh -o ConnectTimeout=10 -o BatchMode=yes <host> bash -lc <quoted-cmd>`. `bash -lc` ensures the remote login shell loads PATH so `claude` resolves on the VPS.
- Remote project root: defaults to `~/htdocs/<name>`. Override globally via env var `ROUTER_REMOTE_HTDOCS` (e.g. `/var/www`) when launching the MCP server.
- Quoting: every interpolated value (project name, question, max_turns) is run through `shlex.quote` before assembly. No raw f-string concatenation into shell commands.
- Timeouts: 10s SSH connect, 90s total for `ask_project` / `delegate_task` (vs 60s local) to absorb the SSH handshake. Connection errors (timeout, refused, unknown host, permission denied, host key) surface as plain `Error: SSH to '<host>' failed: ...` strings — never stack traces.
- Discovery: `list_hosts()` reads `~/.ssh/config` and returns Host aliases (wildcards filtered out) so the main agent can pick a target.

### Pre-flight on each remote VPS

For remote calls to actually succeed, on every host you intend to target:

1. Install Claude Code: `npm i -g @anthropic-ai/claude-code` (or your usual install path).
2. Authenticate: run `claude` once interactively to complete login. **This counts as a separate Anthropic seat** — you are paying per active host.
3. Make sure `~/htdocs/<project>` (or your `ROUTER_REMOTE_HTDOCS` override) actually exists, with the project's `CLAUDE.md` / Serena memories in place. Otherwise the subagent has no context.
4. Confirm passwordless SSH from Jarvis to the host (`BatchMode=yes` is set, so password prompts will fail fast rather than hang).

## v1 limits

- Read-only delegation (`allow_writes=True` → error), local and remote.
- stdio transport only (Jarvis local).
- Sequential calls (no parallel).
- 60s local / 90s remote subprocess timeout.
- 800-word output cap (full output dumped to `/tmp/router-*.md` if exceeded).
- Remote `list_projects` returns a flat list of directory names — the rich metadata (git log, Serena flags) is local-only because gathering it remotely would mean N round trips.

## Architecture

See `docs/architecture-project-router-mcp.md`.

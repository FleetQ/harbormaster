# project-router-mcp

Local MCP server that routes questions and tasks to per-project Claude Code subagents under `~/htdocs/`.

## Why

You work across many projects, each with its own `CLAUDE.md` and Serena memories. Switching cwd loses context. This router lets the **main** Claude Code session ask any project a question without changing directory — the project's subagent loads its own memory, answers, and returns a summary.

Inspired by Google's A2A protocol pattern, but local-only and built on the tools you already have (Claude Code subagents + Serena memories).

## Tools

| Tool | Purpose | Cost |
|---|---|---|
| `list_projects()` | Enumerate `~/htdocs/*` projects with metadata | ~50ms |
| `project_status(name)` | Git log, Serena memory headers, recent log tails | ~200ms |
| `ask_project(name, question, max_turns=5)` | Spawn `claude -p` in project cwd, return ≤800 word summary | ~30s |
| `delegate_task(name, task, deliverable, allow_writes=False)` | Read-only delegation; v1 fails closed for writes | ~60s |

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

## v1 limits

- Read-only delegation (`allow_writes=True` → error)
- stdio transport only (Jarvis local)
- Sequential calls (no parallel)
- 60s subprocess timeout
- 800-word output cap (full output dumped to `/tmp/router-*.md` if exceeded)

## Architecture

See `docs/architecture-project-router-mcp.md`.

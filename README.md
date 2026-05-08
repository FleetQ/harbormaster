# Harbormaster

> MCP server that routes Q&A across all your projects — locally or over SSH. **Part of the [FleetQ](https://fleetq.net) ecosystem.**

[![PyPI](https://img.shields.io/pypi/v/harbormaster-mcp.svg?label=harbormaster-mcp)](https://pypi.org/project/harbormaster-mcp/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Status](https://img.shields.io/badge/status-alpha-orange.svg)](#status)

## What it does

You work across many projects, each with its own `CLAUDE.md` and Serena memories. Switching cwd loses context. Harbormaster lets one Claude Code session ask any project a question without changing directory — the project's subagent loads its own memory, answers, and returns a summary.

Optional SSH fan-out lets the same tools target remote VPS hosts. Optional FleetQ adapter makes Harbormaster a first-class citizen of the FleetQ Bridge ecosystem (Platform Tool, A2A Agent Cards, federated knowledge graph).

## Tools

| Tool | Purpose | Cost |
|---|---|---|
| `list_projects(host=None)` | Enumerate configured projects (local) or remote dir listing (SSH). | ~50 ms / ~1 s |
| `list_hosts()` | Configured `[hosts]` + `~/.ssh/config` Host aliases. | ~5 ms |
| `project_status(name, host=None)` | Git log, Serena memories, log tails. | ~200 ms / ~2 s |
| `ask_project(name, question, max_turns=5, host=None)` | Spawn `claude -p` in project cwd, return ≤ 800-word summary. | ~30 s / ~90 s |
| `delegate_task(name, task, deliverable, allow_writes=False, host=None)` | Read-only delegation; v1 fails closed for writes. | ~60 s / ~90 s |
| `fan_out_ask(question, project_filter=None, host_filter=None, max_concurrency=5, max_turns=3)` | Parallel multi-project Q&A. Returns one section per target. | ~`max_turns × claude_p_time` × ⌈targets/max_concurrency⌉ |

More tools (`recall_qa`, …) land in v1.1–1.2. See [`docs/architecture-harbormaster.md`](docs/architecture-harbormaster.md).

## Install

```bash
pipx install harbormaster-mcp
# or run without install:
uvx harbormaster-mcp
```

Register in Claude Code:

```bash
claude mcp add --scope user harbormaster harbormaster-mcp
```

Or in Claude Desktop (`~/Library/Application Support/Claude/claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "harbormaster": {
      "command": "/opt/homebrew/bin/harbormaster-mcp",
      "env": {}
    }
  }
}
```

### HTTP / SSE transport

For remote MCP clients or running outside the desktop client, Harbormaster can speak SSE / streamable-http instead of stdio. **A bearer token is required** — there is no auth-disabled HTTP mode.

```bash
export HARBORMASTER_MCP_TOKEN=$(python -c 'import secrets; print(secrets.token_urlsafe(32))')
harbormaster-mcp --transport sse --host 127.0.0.1 --port 7532
# or the new MCP spec transport:
harbormaster-mcp --transport streamable-http --port 7532
```

Clients send the token as `Authorization: Bearer <token>`. Missing or wrong tokens return 401.

Override the env-var name with `--auth-token-env MY_VAR` if you keep secrets under a different name. Use `--host 0.0.0.0` only if you understand the implications — the bearer token is the only thing between the open port and your projects.

Run `harbormaster-mcp --help` for the full flag set.

## Configure

Zero-config by default — Harbormaster discovers projects under `~/htdocs/*` if it exists. For any other layout, drop a TOML file at `~/.config/harbormaster/config.toml`:

```toml
[projects]
glob = ["~/code/*", "~/work/*"]
exclude = ["**/node_modules/**", "**/vendor/**"]

[hosts.friday]
ssh_host = "katsarov-server.local"
remote_htdocs = "~/htdocs"

[hosts.hetzner-1]
ssh_host = "hetzner-1.example.com"
remote_htdocs = "/var/www"
```

A per-project override at `./.harbormaster.toml` in your cwd takes precedence over the user-level config.

Full schema and all options: [`docs/architecture-harbormaster.md` §3](docs/architecture-harbormaster.md).

## Remote hosts

Every project-targeting tool accepts an optional `host` parameter. With `host` set, Harbormaster runs the equivalent command on that SSH host:

```
> ask_project(name="pricex", question="quick health check?", host="friday")
[ssh friday bash -lc 'cd ~/htdocs/pricex && claude -p ...']
```

**Pre-flight on each remote host**:

1. Install Claude Code: `npm i -g @anthropic-ai/claude-code`.
2. Authenticate once: `claude` (this is a separate Anthropic seat per host).
3. Ensure project paths exist with their `CLAUDE.md` / `.serena/` in place.
4. Confirm passwordless SSH from your machine (`BatchMode=yes` is enforced).

## v1 limits

- Read-only delegation (`allow_writes=True` returns an error).
- 60 s local / 90 s remote subprocess timeout.
- 800-word output cap (full output dumped to `/tmp/harbormaster-*.md` on truncation).
- Remote `list_projects` returns a flat list of directory names (rich metadata is local-only — gathering it remotely would mean N round-trips).

## Status

**v1.0.0a3** — Backend Protocol tightening, HTTP/SSE transport, e2e test infrastructure, fan-out synthesis shipped 2026-05-08. The 6-week roadmap to general availability:

| Phase | Weeks | Focus |
|-------|-------|-------|
| v1.0 | 1–2 | Local + SSH + Live UI scaffold + PyPI alpha |
| v1.1 | 3–4 | FleetQ Bridge / Platform Tool / A2A integration |
| v1.2 | 5–6 | Q&A history, federated KG, auto project graph |

See [`docs/design-harbormaster.md`](docs/design-harbormaster.md) for the full design.

## Lineage

Harbormaster v1.0 grew out of `project-router-mcp` v0.1 (2026-05-08). v0.1 git history is preserved on this repository — the v0.1 single-file server lived at `src/server.py` and remains in commits prior to the v1.0 scaffolding refactor.

## Architecture

Single Python process hosting an MCP server (stdio + HTTP/SSE), an embedded Live UI, and an optional FleetQ adapter. Pluggable backend per host (default: `claude -p`). All shell-bound strings pass through `shlex.quote`.

Detailed component diagrams, transport choices, and integration contract: [`docs/architecture-harbormaster.md`](docs/architecture-harbormaster.md).

## License

MIT — see [LICENSE](LICENSE).

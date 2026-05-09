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
| `recall_qa(question, top_k=5, host=None, project=None, min_similarity=0.6)` | Semantic recall over prior `ask_project` / `delegate_task` answers (v1.2 phase 1). Opt-in via `[history] enabled = true`. | ~50 ms (FTS5) / ~150 ms (vec, after model warm-up) |
| `project_graph(format="json", include_dev_deps=False)` | Cross-project dependency graph from manifest parsing (v1.2 phase 3). Edges only when a dep name matches another known project. Returns nodes + edges + optional Mermaid markup. | ~100 ms / ~10 ms cached |

See [`docs/architecture-harbormaster.md`](docs/architecture-harbormaster.md) for the full design (Q&A history is §17, project graph is §18).

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

### Live UI (optional)

Install with the `[ui]` extra and run the dashboard alongside (or instead of) the MCP server:

```bash
pipx install 'harbormaster-mcp[ui]'
harbormaster-ui --port 7531
# open http://127.0.0.1:7531/
```

v1.0.0a4 ships:

- **Dashboard** at `/` — project grid with framework / git / Serena / CLAUDE.md badges (HTMX + Alpine + Tailwind via CDN, ~no build step).
- **`GET /api/projects`** — JSON list of every project Harbormaster discovers (use this to script your own dashboards).
- **`GET /api/health`** — `{"status":"ok","version":"..."}` for liveness probes.

The UI is a separate process from the MCP server. Run both — they read the same TOML config so projects discovered by one are visible to the other. SSE feed of live MCP queries lands in v1.0.0a5.

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

## Streaming

`POST /mcp/{server}` accepts `Accept: text/event-stream` for incremental output. Long-running tools (`ask_project`, `delegate_task`, `fan_out_ask`, all 30–90s) emit heartbeat events on the wire while they run, then a final `result` event with the same MCP envelope JSON-mode would return. `ask_project` against a local project additionally emits per-token `chunk` events as `claude -p --output-format stream-json` produces them.

Direct curl example (bypasses FleetQ — for testing or a custom consumer):

```bash
curl -N -X POST http://127.0.0.1:7531/mcp/harbormaster \
  -H 'Accept: text/event-stream' \
  -H 'Content-Type: application/json' \
  -d '{"method":"tools/call","params":{"name":"ask_project","arguments":{"name":"alpha","question":"summarize"}}}'
```

Through the FleetQ Bridge, set `stream: true` in the request body — the Bridge forwards `text/event-stream` bytes verbatim with `X-Accel-Buffering: no` so reverse proxies don't buffer.

JSON mode (no `Accept: text/event-stream`, no `stream` flag) is unchanged — fully backward-compatible.

## v1 limits

- Read-only delegation (`allow_writes=True` returns an error).
- 60 s local / 90 s remote subprocess timeout.
- 800-word output cap (full output dumped to `/tmp/harbormaster-*.md` on truncation).
- Remote `list_projects` returns a flat list of directory names (rich metadata is local-only — gathering it remotely would mean N round-trips).
- Per-token `chunk` events are local-only — `ask_project` over SSH still falls back to heartbeat + final result (remote stdout demux is a separate refactor).

## Status

**v1.0.0a17** — v1.2 phase 1 (Q&A history) shipped 2026-05-09. New
`recall_qa` MCP tool exposes semantic recall over every past
`ask_project` / `delegate_task` trajectory, persisted to a per-host
sqlite-vec store. Default embedding backend is fastembed
(BAAI/bge-small-en-v1.5, runs locally, ~50MB ONNX); falls back to
FTS5 / bm25 when the optional `[history]` extra is missing. Opt-in via
`[history] enabled = true`. See [`docs/architecture-harbormaster.md` §17](docs/architecture-harbormaster.md).

| Phase | Status | Focus |
|-------|--------|-------|
| v1.0 | **Complete** (a8–a14) | Local + SSH + Live UI + PyPI alpha publish pipeline + SSE chunk streaming on both sides + FleetQ Bridge HTTP-tunnel mode |
| v1.1 | **Complete** (a13–a16) | Platform Tool seeder ✅ a13 · A2A Agent Card per project ✅ a15 · live FleetQ smoke ✅ a11 · `update_endpoints` watch ✅ a10 · Memory writeback ✅ a16 · operator guide ✅ a16 |
| v1.2 | **Complete** (a17–a20) | Q&A history with sqlite-vec + fastembed ✅ a17 · auto project graph from manifest parsing ✅ a18 · federated KG via FleetQ KnowledgeGraph ✅ a19 · cross-session memory recall via auto-grounding ✅ a20 |

The original 6-week roadmap is largely complete on the v1.0 axis. v1.1 has shipped its biggest deliverables (Bridge integration, streaming end-to-end, Platform Tool seed, A2A cards). v1.2 (compounding) is the remaining phase before dropping the alpha tag and tagging `v1.0.0` GA.

See [`docs/design-harbormaster.md`](docs/design-harbormaster.md) for the full design.

## Lineage

Harbormaster v1.0 grew out of `project-router-mcp` v0.1 (2026-05-08). v0.1 git history is preserved on this repository — the v0.1 single-file server lived at `src/server.py` and remains in commits prior to the v1.0 scaffolding refactor.

## Architecture

Single Python process hosting an MCP server (stdio + HTTP/SSE), an embedded Live UI, and an optional FleetQ adapter. Pluggable backend per host (default: `claude -p`). All shell-bound strings pass through `shlex.quote`.

Detailed component diagrams, transport choices, and integration contract: [`docs/architecture-harbormaster.md`](docs/architecture-harbormaster.md).

## FleetQ Bridge integration (optional)

Install with the `[fleetq]` extra and Harbormaster can register itself as a Bridge daemon in your FleetQ deployment, advertising its 6 MCP tools to the platform:

```bash
pipx install 'harbormaster-mcp[fleetq]'
```

In your config TOML:

```toml
[fleetq]
enabled = true
register_as_bridge = true
base_url = "https://app.fleetq.net"   # or your self-hosted FleetQ URL
api_token_env = "FLEETQ_API_TOKEN"    # env var holding the Sanctum token
heartbeat_interval = 30               # seconds between heartbeats
```

Then export your Sanctum token (must have a `team:<uuid>` ability) and run the MCP server:

```bash
export FLEETQ_API_TOKEN=...
harbormaster-mcp
```

Harbormaster shows up in your FleetQ Connections UI as `harbormaster on <hostname>`. v1.0.0a6 ships **register + heartbeat + disconnect**; the reverse-WebSocket relay channel for incoming MCP tool calls lands in v1.0.0a7+.

Discovered contract reference: [`docs/fleetq-bridge-contract.md`](docs/fleetq-bridge-contract.md).

## Releasing

PyPI publishing is automated via Trusted Publishing (OIDC) — no API tokens in the repo. Tag-pushes to `v*` trigger `.github/workflows/publish.yml`. Setup steps and the release checklist live in [`docs/publishing.md`](docs/publishing.md).

## License

MIT — see [LICENSE](LICENSE).

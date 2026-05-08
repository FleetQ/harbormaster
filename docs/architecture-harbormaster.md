# Harbormaster Architecture

**Status**: Plan phase
**Sprint**: 2026-05-08
**Reads**: `docs/design-harbormaster.md`
**Feeds**: `docs/test-plan-harbormaster.md`, Build phase
**License**: MIT
**Repo**: github.com/FleetQ/harbormaster
**Package**: `harbormaster-mcp` on PyPI
**Time budget**: 6 weeks (v1.0 weeks 1-2, v1.1 weeks 3-4, v1.2 weeks 5-6)

---

## 1. Overview

Single Python process hosting:

1. **MCP server** over stdio (default for Claude Code / Desktop) and HTTP/SSE (for remote MCP clients and the Live UI's tool calls).
2. **Live UI** (FastAPI + HTMX + Alpine + Tailwind, ~500 LOC frontend, single port).
3. **Background worker** for SSH dispatch and trajectory persistence (asyncio task pool, no separate process).
4. **Optional FleetQ adapter** (`harbormaster-mcp[fleetq]` extra) for Bridge / Memory / KG integration.

**Design principles**:

- **Standalone OSS works fully** without FleetQ. FleetQ integration is purely additive.
- **One process, many transports** — stdio + HTTP/SSE share the same MCP tool registry. No duplication.
- **Config-driven discovery**, not convention. The hard-coded `~/htdocs/*` of v0.1 is gone.
- **Pluggable backends** from day one. `claude` is default; `codex`/`aider`/`gemini-cli` follow the same contract.
- **Local-first storage**. sqlite-vec for v1.0. pgvector or FleetQ Memory only when the user opts in.
- **Trust no input**. All shell-bound strings go through `shlex.quote`. All UI output is sanitized.

---

## 2. Module layout

```
harbormaster/
├── pyproject.toml                     # PEP 621 packaging, MIT license, deps
├── README.md
├── LICENSE                            # MIT
├── docs/
│   ├── design-harbormaster.md
│   ├── architecture-harbormaster.md   # this file
│   ├── test-plan-harbormaster.md
│   ├── configuration.md
│   └── fleetq-integration.md
├── src/harbormaster/
│   ├── __init__.py
│   ├── __main__.py                    # `python -m harbormaster`
│   ├── server.py                      # FastMCP + FastAPI wiring
│   ├── config.py                      # TOML loader, schema, defaults
│   ├── tools/                         # MCP tool implementations
│   │   ├── __init__.py
│   │   ├── projects.py                # list_projects, project_status
│   │   ├── ask.py                     # ask_project, fan_out_ask
│   │   ├── delegate.py                # delegate_task
│   │   └── hosts.py                   # list_hosts
│   ├── backends/
│   │   ├── __init__.py
│   │   ├── base.py                    # BackendInterface (Protocol)
│   │   ├── claude.py                  # default — `claude -p` over subprocess
│   │   ├── codex.py                   # post-v1.0
│   │   ├── aider.py                   # post-v1.0
│   │   └── gemini.py                  # post-v1.0
│   ├── ssh/
│   │   ├── __init__.py
│   │   ├── command.py                 # safe ssh command builder (shlex)
│   │   ├── runner.py                  # async SSH subprocess runner
│   │   └── hosts.py                   # ssh_config parsing + config overrides
│   ├── ui/
│   │   ├── __init__.py
│   │   ├── routes.py                  # FastAPI routes
│   │   ├── sse.py                     # SSE event hub (asyncio.Queue per client)
│   │   ├── templates/                 # Jinja2 templates (HTMX partials)
│   │   └── static/                    # Tailwind output, Alpine, htmx.min.js
│   ├── storage/
│   │   ├── __init__.py
│   │   ├── schema.sql                 # sqlite-vec schema
│   │   ├── trajectories.py            # write/read Q&A history
│   │   └── dedup.py                   # semantic dedup (v1.2)
│   ├── fleetq/                        # optional [fleetq] extra
│   │   ├── __init__.py
│   │   ├── bridge.py                  # POST register/heartbeat/endpoints
│   │   ├── memory.py                  # write trajectories to FleetQ Memory
│   │   └── a2a.py                     # publish A2A Agent Cards
│   └── observability/
│       ├── __init__.py
│       ├── logging.py                 # structlog config
│       └── audit.py                   # append-only audit log
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── e2e/
│   └── fixtures/
└── .github/
    └── workflows/
        ├── ci.yml                     # lint + test on push
        └── release.yml                # PyPI publish on tag
```

---

## 3. Configuration (TOML)

Default location: `${XDG_CONFIG_HOME:-~/.config}/harbormaster/config.toml`. Per-project override: `./.harbormaster.toml` in cwd takes precedence for any key set there.

```toml
# ~/.config/harbormaster/config.toml

[server]
ui_port = 7531                  # Live UI port (HTTP/SSE)
mcp_http_port = 7532            # MCP HTTP/SSE transport (separate from UI)
log_level = "info"
trajectory_retention_days = 90

[projects]
glob = ["~/htdocs/*", "~/work/*"]
exclude = ["**/node_modules/**", "**/vendor/**", "**/.git/**"]
require_marker = false          # if true, only dirs containing CLAUDE.md or .serena/

[backends.claude]                # default backend
enabled = true
binary = "claude"               # PATH lookup
extra_args = ["-p"]
timeout_local = 60               # seconds
timeout_remote = 120
output_word_cap = 800

[backends.codex]                 # post-v1.0
enabled = false

[hosts.friday]                   # SSH host
ssh_host = "katsarov-server.local"
remote_htdocs = "~/htdocs"
backend = "claude"               # which backend on this host
connect_timeout = 10
total_timeout = 120

[hosts.hetzner-1]
ssh_host = "hetzner-1.example.com"
remote_htdocs = "/var/www"
backend = "claude"

[storage]
db_path = "${XDG_DATA_HOME:-~/.local/share}/harbormaster/harbormaster.db"
enable_dedup = false             # v1.2

[ui]
auth_required = false            # v1: localhost only
auth_token_env = "HARBORMASTER_UI_TOKEN"  # if auth_required
theme = "system"

[fleetq]                         # all keys optional
enabled = false                  # explicit opt-in
base_url = "https://app.fleetq.net"
api_token_env = "FLEETQ_API_TOKEN"
write_trajectories = true
publish_a2a_cards = false
register_as_bridge = false
heartbeat_interval = 30

[telemetry]
enabled = false                  # opt-in only
endpoint = "https://telemetry.fleetq.net/harbormaster"
```

**Schema validation**: pydantic v2 model `HarbormasterConfig`. Invalid config = startup abort with explicit error pointing at the offending key.

---

## 4. MCP tools

All tools are registered against a single FastMCP server, exposed over both stdio and HTTP/SSE.

| Tool | v1 phase | Purpose |
|------|----------|---------|
| `list_projects(host=None)` | v1.0 | Enumerate projects from config glob (local) or remote `ls` (SSH). |
| `list_hosts()` | v1.0 | Return configured + ssh_config-discovered hosts. |
| `project_status(name, host=None)` | v1.0 | Git log, Serena memory headers, log tails. |
| `ask_project(name, question, max_turns=5, host=None, backend=None)` | v1.0 | Spawn subagent, return ≤800-word summary. |
| `fan_out_ask(question, project_filter=None, host_filter=None, max_concurrency=5)` | v1.0 | Parallel multi-project Q&A with map-reduce synthesis. |
| `delegate_task(name, task, deliverable, allow_writes=False, host=None)` | v1.0 | Read-only delegation; remote writes always rejected. |
| `recall_qa(query, top_k=5)` | v1.2 | Semantic recall of past Q&As. |

Schemas use pydantic models. JSON Schema is auto-generated for MCP advertisement.

**Error envelope** (consistent across tools):

```json
{
  "ok": false,
  "error": {
    "code": "ssh_connect_failed | timeout | project_not_found | backend_failure | invalid_config",
    "message": "human-readable",
    "context": { "host": "friday", "project": "pinporn" }
  }
}
```

---

## 5. Backend abstraction

```python
# src/harbormaster/backends/base.py

class BackendInterface(Protocol):
    name: str

    async def ask(
        self,
        prompt: str,
        cwd: Path,
        max_turns: int,
        timeout: int,
    ) -> BackendResult: ...

    def supports_remote(self) -> bool: ...

    def build_remote_command(
        self, prompt: str, remote_cwd: str, max_turns: int
    ) -> list[str]: ...  # for SSH execution


@dataclass
class BackendResult:
    ok: bool
    output: str | None
    truncated: bool
    duration_ms: int
    cost_estimate_usd: float | None
    error: BackendError | None
```

Default: `ClaudeBackend` (`claude -p <prompt>` with structured output parsing tolerant of leading login banners — already prototyped in v0.1 SSH branch). Codex/Aider/Gemini follow the same contract; not in v1.0 ship.

---

## 6. Transport layer

| Transport | Use case | Auth |
|-----------|----------|------|
| stdio | Default for Claude Code / Desktop registration | Process-bound; whoever spawns owns it |
| HTTP/SSE | Remote MCP clients, mobile, multi-machine | Bearer token (`HARBORMASTER_MCP_TOKEN`); v1 supports localhost-only mode |

Both wired to the same FastMCP `Server` instance. Single tool registry, single config, single trajectory log.

The Live UI (§7) does **not** call MCP tools over HTTP/SSE — it imports them as Python functions to avoid the round trip. SSE is reserved for streaming **answers** to the UI, not RPC.

---

## 7. Live UI

**Stack**: FastAPI · HTMX · Alpine.js · Tailwind v4 (CDN in dev, JIT-compiled to single CSS in prod) · Jinja2 templates · SSE for live data.

**Routes**:

| Method | Path | Purpose |
|--------|------|---------|
| `GET /` | Dashboard (project grid + sidebar fleet view) |
| `GET /projects/{name}` | Project detail (memories, history, ask form) |
| `POST /projects/{name}/ask` | HTMX form post; spawns ask, returns SSE stream URL |
| `GET /stream/{run_id}` | SSE stream for in-flight ask |
| `GET /history` | Searchable Q&A history table |
| `GET /history/{run_id}` | Full transcript + replay button |
| `POST /history/{run_id}/replay` | Re-execute past question |
| `GET /hosts` | Fleet view |
| `GET /memories/{name}` | Memory inspector (read-only) |
| `GET /api/events` | Global SSE stream of all activity |

**SSE event schema** (`text/event-stream`, one event per line group):

```
event: query_started
data: {"run_id":"01HJ...","project":"pinporn","host":"local","question":"...","ts":"2026-05-08T..."}

event: query_chunk
data: {"run_id":"01HJ...","chunk":"...streaming markdown..."}

event: query_completed
data: {"run_id":"01HJ...","duration_ms":12450,"truncated":false,"tokens":3210}

event: query_failed
data: {"run_id":"01HJ...","error":{"code":"timeout","message":"..."}}
```

**Security**:

- v1: localhost-only. UI binds to `127.0.0.1`.
- All rendered answers pass through `bleach` server-side. Inline scripts forbidden by CSP.
- HTMX requests include CSRF token from cookie.
- Replay button confirms via Alpine modal before re-spawning.

**Mockup hierarchy**:

```
/ (dashboard)
├── Top bar: Harbormaster logo · search · cost panel mini · settings
├── Sidebar: Fleet view (local + remote hosts with status dots)
└── Main:
    ├── Live query feed (top, SSE-driven, ≤5 most recent)
    └── Project grid (cards: name · last commit · framework · memories count · "Ask" button)
```

---

## 8. Storage

**v1.0**: sqlite-vec at `${XDG_DATA_HOME:-~/.local/share}/harbormaster/harbormaster.db`.

Tables:

```sql
CREATE TABLE runs (
  id TEXT PRIMARY KEY,            -- UUIDv7
  project TEXT NOT NULL,
  host TEXT NOT NULL,             -- 'local' or alias
  backend TEXT NOT NULL,          -- 'claude' / 'codex' / ...
  question TEXT NOT NULL,
  answer TEXT,
  truncated INTEGER NOT NULL DEFAULT 0,
  duration_ms INTEGER,
  tokens_in INTEGER,
  tokens_out INTEGER,
  cost_usd REAL,
  status TEXT NOT NULL,           -- 'started' / 'completed' / 'failed'
  error TEXT,
  started_at TEXT NOT NULL,       -- ISO 8601
  completed_at TEXT
);

CREATE INDEX idx_runs_project_started ON runs(project, started_at DESC);
CREATE INDEX idx_runs_host_started ON runs(host, started_at DESC);

-- v1.2: vector embeddings
CREATE VIRTUAL TABLE run_vectors USING vec0(
  run_id TEXT PRIMARY KEY,
  embedding FLOAT[1024]
);
```

**Retention**: configurable, default 90 days. Background task prunes daily.

**v1.1+ (FleetQ on)**: trajectories also written to FleetQ Memory domain via `POST /api/v1/memory`. Local sqlite remains source of truth; FleetQ is replicated read model.

---

## 9. SSH layer

**Command builder** (`ssh/command.py`): every interpolated value passes through `shlex.quote`. SSH options enforced:

- `-o ConnectTimeout=10`
- `-o BatchMode=yes` (no password prompts)
- `-o ControlMaster=auto -o ControlPath=~/.ssh/cm-%h-%p-%r -o ControlPersist=60s` (connection reuse for fan-out)

**Remote execution**: `bash -lc <quoted-command>` so PATH loads on the remote.

**Errors** mapped to typed exceptions:

| Exit code / signal | Mapped error |
|-----|------|
| 255 + "Connection refused" | `SshConnectFailed` |
| 255 + "Connection timed out" | `SshTimeout` |
| 255 + "Permission denied" | `SshAuthFailed` |
| Custom non-zero from remote | `BackendFailure` (with stderr tail) |
| Timeout from our wrapper | `OperationTimeout` |

**Fuzz test invariant**: no string passed by the user can change the structure of the executed command. Property tests with `hypothesis` generate adversarial project names / questions and assert the parsed `argv` length stays constant.

---

## 10. FleetQ integration (v1.1)

Optional, configured via `[fleetq]` section.

**Bridge handshake**:

```
on startup (if fleetq.register_as_bridge):
  POST /api/v1/bridge/register
    headers: Authorization: Bearer <token>
    body: {
      "name": "harbormaster",
      "version": "1.1.0",
      "capabilities": ["mcp_stdio", "fan_out_ask", "ssh_routing"],
      "endpoints": [...],
      "host_aliases": ["friday", "hetzner-1", ...]
    }
  ← 201 { "bridge_id": "...", "heartbeat_url": "...", "deregister_url": "..." }

every fleetq.heartbeat_interval seconds:
  POST <heartbeat_url>
    body: { "queue_depth": N, "uptime_s": ..., "version": "..." }

on graceful shutdown:
  DELETE <deregister_url>
```

Exact payload schemas to be confirmed against `agent-fleet/cloud/routes/api.php` Bridge controller during v1.1 build. Plan-phase assumption: shape follows REST conventions visible in `app/Domain/Bridge/`.

**Memory writeback**: every completed run posts a normalized trajectory:

```
POST /api/v1/memory
  body: {
    "scope": "project:<name>",
    "kind": "qa_trajectory",
    "data": { question, answer, duration_ms, ... },
    "metadata": { "harbormaster_run_id": "...", "host": "..." }
  }
```

**A2A cards (optional)**: per project, publish an Agent Card to `POST /a2a/agents/register` describing the project's tools, descriptions, supported skills.

---

## 11. Observability

- **Structured logs** via `structlog`. JSON in prod, key-value in dev. Every run logged with `run_id`, `project`, `host`, `duration_ms`, `status`.
- **Audit log**: append-only file at `${XDG_DATA_HOME}/harbormaster/audit.jsonl`. One line per write/delegation. Tamper-resistant by virtue of being read-mostly.
- **Metrics**: optional Prometheus exporter at `/metrics` (UI port). Counters: `harbormaster_runs_total{status,host,backend}`, histogram `harbormaster_run_duration_seconds`. Off by default.
- **OTEL**: not in v1.

---

## 12. Process model

Single-process by default. Async event loop runs:

1. MCP stdio handler (if launched via stdio).
2. FastAPI app (UI + MCP HTTP/SSE).
3. SSH dispatcher (asyncio task pool, `Semaphore(max_concurrency=5)`).
4. Heartbeat / FleetQ adapter (if enabled).
5. Trajectory writer + retention pruner (cron-style).

**No supervisor needed**. systemd / launchd unit files shipped as templates for users who want resilient running.

---

## 13. Performance budget

| Operation | v0.1 measured | v1 target |
|-----------|---------------|-----------|
| `list_projects` (52 projects) | 857 ms | < 200 ms (cached, invalidated on FS change) |
| `project_status` | 170 ms | < 150 ms |
| `ask_project` (local, claude) | ~30 s | unchanged (bottleneck is the backend) |
| `ask_project` (SSH) | n/a | ≤ 35 s (5s SSH overhead) |
| `fan_out_ask` (10 projects, max_concurrency=5) | n/a | ≤ 60 s |
| UI cold start | n/a | < 800 ms TTFB |
| SSE event delivery latency | n/a | < 50 ms p95 |

---

## 14. Error handling philosophy

- **Boundaries validate**: SSH, MCP, HTTP, config load.
- **Internals trust**: no defensive checks between modules in the same package.
- **Errors surface, not swallow**: every error becomes a typed exception with `error.code`. The MCP envelope and the UI both render `error.code` so users can google it.
- **No retries by default**. Retries hide bugs and amplify cost. Caller (Claude Code, FleetQ) decides retry policy.

---

## 15. Build phase staging (week-by-week)

| Week | Focus | Deliverable |
|------|-------|-------------|
| 1 | Repo rename, packaging, config, backends abstraction, dual transport | `harbormaster-mcp` installs; existing tools work via TOML config |
| 2 | SSH hardening, fan_out_ask, Live UI scaffold, SSE plumbing | UI shows project grid + live feed; ssh tests pass; PyPI alpha |
| 3 | FleetQ Bridge handshake + heartbeat | Registered visible in FleetQ instance |
| 4 | Platform Tool seeder PR into agent-fleet, Memory writeback | Activate-via-FleetQ flow works end to end |
| 5 | Q&A history dedup (sqlite-vec), recall_qa tool | Recall works locally |
| 6 | KG federation polish, A2A cards, docs/site, v1.0.0 GA tag | Public launch (Show HN, blog, FleetQ marketplace announcement) |

---

## 16. Out-of-architecture (decisions deferred)

- Tauri / Electron native wrapper.
- Multi-user UI (post-v1).
- Plugin system (post-v2).
- Non-Python backend implementations (e.g., Rust core).
- gRPC transport.

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

## 16. Reverse-proxy / nginx configuration for streaming

The SSE chunk stream on `/mcp/{server}` (harbormaster) and the
FleetQ Bridge's `/api/v1/bridge/mcp/call` (agent-fleet) both
depend on **buffering being disabled** at every reverse proxy
in the path. Without that, chunks pile up in the proxy's buffer
and the user sees one big response after the whole stream
completes — defeating the streaming UX.

The harbormaster daemon and the FleetQ Bridge controller both
emit `X-Accel-Buffering: no` on streaming responses, but the
proxy must honour it. nginx 1.5.6+ does so by default for
`proxy_buffering`. Other proxies (Cloudflare, Tailscale Funnel,
Traefik) usually pass it through but verify on first deployment.

### nginx (ahead of harbormaster-ui or FleetQ)

```nginx
location /mcp/ {
    proxy_pass http://harbormaster_upstream;
    proxy_http_version 1.1;
    proxy_set_header Connection "";
    proxy_buffering off;          # honour X-Accel-Buffering: no
    proxy_read_timeout 300s;      # tools take 30-90s; need headroom
    proxy_send_timeout 300s;
}

location /api/v1/bridge/mcp/call {
    proxy_pass http://fleetq_upstream;
    proxy_http_version 1.1;
    proxy_set_header Connection "";
    proxy_buffering off;
    proxy_read_timeout 300s;
    proxy_send_timeout 300s;
}
```

### What the daemon does on its end

PHP-FPM and Laravel each maintain an output buffer by default.
The Bridge controller's streaming callback drops them via
`ob_get_clean()` in a guarded loop before the first `flush()`,
so chunks reach the socket as soon as they're emitted. This is
disabled under PHPUnit (Laravel's `TestResponse` maintains its
own buffer around `streamedContent()`).

Python / FastAPI doesn't have the same pre-existing-buffer
problem — sse-starlette's `EventSourceResponse` writes through
to the socket without intermediate buffering.

### Verifying end-to-end

```bash
curl -N -X POST https://harbormaster.example/mcp/harbormaster \
  -H 'Accept: text/event-stream' \
  -H 'Content-Type: application/json' \
  -d '{"method":"tools/call","params":{"name":"ask_project","arguments":{"name":"alpha","question":"summarize"}}}'
```

`event: chunk` lines should appear in the terminal incrementally
(not all at once at the end). If they all arrive together at the
end, a proxy in the path is buffering — start adding
`proxy_buffering off` to each layer until they appear
incrementally.

---

## 17. Q&A history with semantic recall (v1.2 phase 1)

Harbormaster persists every successful `ask_project` / `delegate_task`
trajectory to a per-host sqlite database, indexed by question
embedding. The companion `recall_qa` tool returns prior answers that
semantically match a new question — enabling the main session to
short-circuit duplicate work without re-spawning a `claude -p` subagent.

### Storage layout

One sqlite file per host:

```
~/.harbormaster/
  qa_local.db
  qa_friday.db
  qa_hetzner-1.db
  ...
```

Per-host isolation matches the fact that a question against `friday`'s
copy of `pricex` is semantically different from the same question
against the local copy — different commit, different state, different
configuration. Aggregated cross-host recall is intentionally deferred
to v1.2 phase 4.

### Schema (per-db)

```sql
CREATE TABLE qa_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    question        TEXT NOT NULL,
    answer          TEXT NOT NULL,
    project         TEXT NOT NULL,
    host            TEXT NOT NULL,           -- "local" | host alias
    tool            TEXT NOT NULL,           -- "ask" | "delegate" | ...
    created_at      INTEGER NOT NULL,        -- unix epoch
    duration_ms     INTEGER,                 -- ms in claude -p
    cost_cents      INTEGER,                 -- nullable; populated when stream-json yields cost
    recall_count    INTEGER NOT NULL DEFAULT 0,
    last_recalled_at INTEGER
);

-- vec track (created when sqlite-vec extension loads):
CREATE VIRTUAL TABLE qa_vec USING vec0(embedding float[384]);

-- fts track (always created, used as fallback when vec is missing):
CREATE VIRTUAL TABLE qa_fts USING fts5(
    question, answer,
    content='qa_log', content_rowid='id',
    tokenize='porter unicode61'
);
```

The vec dim (384) matches the default fastembed model
(`BAAI/bge-small-en-v1.5`). Switching dim requires a fresh db file;
we don't migrate vectors across dimensions.

### Embedding backends

| Backend | Trigger | Network | Cost | Quality |
|---------|---------|---------|------|---------|
| `fastembed` (default) | `[history] embedding_backend = "fastembed"` + `[history]` extra installed | One-time model download (~50MB) | $0 | Strong semantic recall |
| `fts5` | `[history] embedding_backend = "fts5"`, OR fastembed missing at runtime | None | $0 | Lexical only (bm25) — weaker semantically but zero-friction |

`get_embedding_backend(config)` falls back from `fastembed` to `fts5`
silently when the package is unavailable so the rest of the feature
keeps working.

### Three-gate opt-in (mirrors the FleetQ writeback pattern from §10)

Before `_maybe_record_qa` even opens a connection:

1. `[history] enabled = true` (default `false`)
2. `[history] log_<tool> = true` (default `true` for all tools — set
   `log_ask_project = false` to silence one tool)
3. The `harbormaster.history` import succeeds (i.e. base sqlite is
   importable; the extension is optional)

All three must pass. Failures inside the store are logged at WARNING
level and never propagate — same fire-and-forget semantics as the
FleetQ writeback. The user's MCP response is already in flight by the
time `_maybe_record_qa` runs.

### Retention

After each insert, `prune(retain_recent_k, retain_top_recalled_r)`
keeps the union of:

- the K most recent rows by `created_at` (default 1000)
- the R most-recalled rows by `recall_count` (default 100)

Defaults give a long tail of "this question came up a lot, even if
it's old" without unbounded growth. Both knobs are
`[history].retain_recent_k` / `[history].retain_top_recalled_r`.

### `recall_qa` MCP tool

```python
recall_qa(
    question: str,
    top_k: int | None = None,        # default from [history].default_top_k (5)
    host: str | None = None,         # default: "local"
    project: str | None = None,
    min_similarity: float | None = None,  # default 0.6 (vec path only)
) -> {
    "enabled": bool,
    "backend": "fastembed" | "fts5" | None,
    "host": str,
    "matches": [{
        "id": int, "question": str, "answer": str,
        "project": str, "host": str, "tool": str,
        "created_at": int, "score": float, "recall_count": int,
    }],
    "message": str | None,    # present on disabled / unavailable
}
```

Vec path: scores are cosine similarity (1.0 = exact, 0.0 = orthogonal).
FTS path: scores are normalized bm25 (`1 / (1 + |bm25|)`), comparable
across queries within the same db but not directly comparable to vec
scores.

### Failure modes (all silent + best-effort)

| Failure | Behavior |
|---------|----------|
| `[history]` extra missing | `recall_qa` returns `{enabled: false, message: "install ..."}`; `_maybe_record_qa` is a no-op |
| sqlite-vec not loadable | Falls back to FTS5 path automatically |
| fastembed missing | Falls back to FTS5 path automatically |
| Embedding dim mismatch | Skips vec insert with WARNING; FTS5 row still written |
| sqlite I/O error during insert | Logs exception, rolls back, returns `None` from `record()` |

### Out of scope for phase 1 (filed for later phases)

- **Cross-host federation**: aggregating recall across all `qa_*.db`
  files. Phase 4 territory after v1.2 phase 2 (FleetQ KG) lands.
- **Embedding upgrade-in-place**: switching `embedding_dim` requires
  starting a fresh db file today; no migration tool ships.

### 17.1 Cross-session memory recall via auto-grounding (v1.2 phase 4)

`harbormaster.tools._grounding.build_grounded_prompt(question, project,
host, config)` prepends a "Prior context" section to `ask_project` /
`delegate_task` prompts with the top-K matches from the per-host
sqlite store — auto-grounds the subagent in past answers without
manual context loading.

Three opt-in gates:
1. `[history] enabled = true`
2. `[history] auto_ground = true` (default `false` — opt-in even when
   history is enabled, since prompt bloat has cost implications)
3. `harbormaster.history` package importable

Failures are silent: missing store, recall errors, or embedding
failures all return the original question unchanged. Same fire-and-
forget semantics as the writeback hooks — better to ask without
context than to fail the tool call.

A character cap (`[history] auto_ground_max_chars`, default 8000 ≈
2k tokens) bounds the prepended context. Matches are sorted by score
descending; lowest-score matches drop first when the cap is hit.
Individual answers > 1500 chars are truncated mid-block.

Wire shape (rendered into the prompt):

```
<<<PRIOR CONTEXT (auto-loaded by harbormaster from past answers)>>>

### Past Q (project=alpha, tool=ask_project, score=0.91)
**Question:** How does authentication work?

**Answer:** JWT-based — see auth.md  …[truncated]

### Past Q (project=alpha, tool=delegate_task, score=0.74)
**Question:** ...
**Answer:** ...

<<<END PRIOR CONTEXT>>>

Tell me about authentication
```

The subagent sees this as plain text inside its single-prompt
`claude -p` invocation. No new MCP tool, no new endpoint — pure
prompt augmentation in `tools.ask` and `tools.delegate` before
`run_backend` runs.

`fan_out_ask` is intentionally not auto-grounded today — its prompt
runs against many projects in parallel and recall against each one
would multiply per-target latency. Future: per-target grounding via
the same helper, gated by an additional `[history] auto_ground_fan_out`
flag.

## 18. Auto project graph (v1.2 phase 3)

Harbormaster parses the manifest file of every discovered project and
exposes a cross-project dependency graph. No LLM, no FleetQ, no
network — pure file parsing on a per-process in-memory cache, refreshed
on manifest mtime change.

### Supported manifest formats

| Language | File | Name source | Deps source |
|----------|------|-------------|-------------|
| Python | `pyproject.toml` | `[project].name` (PEP 621) or `[tool.poetry].name` | `[project].dependencies` + `[project.optional-dependencies]` |
| JavaScript / TypeScript | `package.json` | `name` | `dependencies` + `devDependencies` + `peerDependencies` |
| PHP | `composer.json` | `name` (vendor/pkg) | `require` + `require-dev` (php / ext-* filtered) |
| Rust | `Cargo.toml` | `[package].name` | `[dependencies]` + `[dev-dependencies]` + `[build-dependencies]` |
| Go | `go.mod` | `module` directive | `require` lines / blocks (indirect deps filtered) |

### Edge filter

Only edges whose target matches **another known project's name** are
emitted. This keeps the graph readable — pure-library deps from npm /
pip / composer / crates.io are not turned into nodes. The matcher
recognises composer-style aliases (`vendor/pkg` matches `pkg` too).

### Wire shape

`GET /api/graph` (UI) and `project_graph(format="json")` (MCP tool):

```json
{
  "projects_discovered": 39,
  "manifests": [
    {"name": "harbormaster-mcp", "language": "python", "path": "/.../harbormaster",
     "manifest_file": "/.../harbormaster/pyproject.toml",
     "version": "1.0.0a17", "description": "...",
     "deps": ["mcp", "pydantic"], "dev_deps": [...]}
  ],
  "graph": {
    "nodes": [{"name": "...", "language": "...", "path": "..."}],
    "edges": [{"src": "alpha", "dst": "beta", "kind": "dep"}]
  },
  "mermaid": "graph LR\n  alpha[\"alpha\"]\n  beta[\"beta\"]\n  alpha --> beta"
}
```

`project_graph(format="mermaid")` adds the `mermaid` field; `format="json"`
omits it.

### Cache invariants

- One `ManifestCache` per process; not shared between `harbormaster-mcp`
  and `harbormaster-ui`. Parsing is fast enough that no IPC is worth the
  coupling.
- Cache key: project root path. Cache value: `(manifest_file, mtime_ns,
  ProjectManifest | None)`. `None` is also cached to skip re-stat'ing
  empty dirs.
- Invalidation: automatic on manifest mtime change; explicit via
  `cache.invalidate(path | None)`.

### Out of scope (filed for later)

- **Dashboard Mermaid widget** — the `/api/graph` endpoint ships now,
  but the rendered widget on `/` is a follow-up. Operators who want the
  visualisation today can hit `/api/graph` and pipe `.mermaid` into any
  Mermaid renderer.
- **Lockfile-driven version pinning** — the parser collects deps but
  not their resolved versions. Adding lockfile parsing (`uv.lock`,
  `package-lock.json`, `composer.lock`, `Cargo.lock`, `go.sum`) is
  v2 territory.
- **Transitive deps** — only direct deps from the manifest. We don't
  resolve transitives (would require a registry call per dep).
- **Cross-host graph** — local-only. SSH host fan-out is v1.2 phase 4
  territory after the FleetQ KG lands.

## 19. Federated KnowledgeGraph via FleetQ (v1.2 phase 2)

Builds on the a16 Memory writeback hook. After every successful
`ask_project` / `delegate_task`, harbormaster runs three heuristic
extractors over the answer text and POSTs the resulting triples to
FleetQ at `/api/v1/memory` with a `type: "kg_triple"` discriminator.
No new endpoint, no FleetQ-side schema change required for the first
cut — the discriminator gives FleetQ a clear classifier when it
later separates trajectories from triples into distinct domains.

### Three heuristic extractors

| Predicate | Source pattern | Confidence |
|-----------|----------------|------------|
| `mentions` | A known project name appears as a token in the answer (composer-style `vendor/pkg` aliased to bare `pkg` too) | 0.6 |
| `uses` | "uses the X library" / "depends on X" / "requires X" / "built on X" | 0.55 |
| `exposes` | HTTP-method-prefixed paths: "GET /api/foo" / "POST /v1/bar" | 0.7 |

Why heuristic, not LLM-based: the cost-per-call must be near-zero so
this can run on every `ask_project`. An LLM call would double our
`claude -p` spend per tool invocation. Triples carry a confidence
score so downstream consumers (FleetQ, future cross-session recall)
can filter the noise.

### Wire shape

```json
POST /api/v1/memory
{
  "type": "kg_triple",
  "tool": "ask_project",
  "project": "alpha",
  "host": "local",
  "content": {
    "subject": "alpha",
    "predicate": "uses",
    "object": "pydantic",
    "confidence": 0.55
  }
}
```

(Same endpoint as a16 trajectory writeback; FleetQ dispatches on
`type` to route triples to the KG domain when KG-aware processing
ships, or stores them as opaque records until then.)

### Three-gate opt-in

Mirrors the FleetQ trajectory writeback pattern (`_maybe_writeback_to_fleetq`):

1. `[fleetq] enabled = true`
2. `[fleetq] write_kg = true` (default `false` — separate from
   `write_trajectories` so operators can ship trajectories without
   the noisier triple stream)
3. The `FLEETQ_API_TOKEN` env var must be non-empty.

The hook (`_maybe_extract_and_writeback_kg` in `tools/_helpers.py`)
sits next to the trajectory writeback in `run_backend`. Same
fire-and-forget semantics: failures inside extraction or POST are
logged at WARNING and never propagate to the user-facing tool call.

### Cap on triples per call

`[fleetq] kg_max_triples_per_call` (default 50) bounds the writeback
cost on dense answers. Extraction order is mentions first (cheapest
+ broadest), then uses, then exposes — so the cap drops the
higher-noise triples first when the answer is dense.

### Out of scope for phase 2 (filed for later)

- **LLM-based triple extraction** — heuristics ship now; an
  LLM-extraction sweep over historical trajectories is v2 territory.
- **Triple deduplication across calls** — a triple posted twice from
  two trajectories lands twice in FleetQ. Deduplication is a
  FleetQ-side concern (or a future client-side "have I seen this
  triple recently" cache).
- **`calls` predicate** (project-A invokes project-B over RPC) —
  needs richer signal than a free-text mention. Likely needs
  `harbormaster.calls` instrumentation in the SSH/HTTP backends.
- **Cross-host triple aggregation** — local-only writes today; the
  FleetQ side aggregates across all harbormasters reporting to it.

## 20. Out-of-architecture (decisions deferred)

- Tauri / Electron native wrapper.
- Multi-user UI (post-v1).
- Non-Python backend implementations (e.g., Rust core).
- gRPC transport.

> **v2.0 update**: Plugin system landed in v2.0 — see [§24
> Plugins](#24-plugins-v20). The "post-v2" guard was satisfied in
> the v2.0 alpha line.

---

# Part B — v9–v19 additions

The sections above (§1–§20) capture the v1.x architecture as drafted
during the original Plan phase (2026-05-08). The sections below are
additive updates documenting the major architectural surfaces that
landed across the autonomous v9 → v18 chain and the in-flight v19
work. Each section names the version that introduced the surface and
the alphas that built it out.

## 21. Dispatcher trace surface (v9.0.0a3 → v17.0.0a1)

The dispatcher is observable end-to-end:

* **`DispatcherStats` singleton** (v9.0.0a2) records per-tool
  counters (`in_flight`, `total_completed`, `total_failed`),
  in-flight spans, and `last_dispatched_at`. Thread-safe; ~2 lock
  acquires per dispatch.
* **`GET /api/dispatcher/status`** exposes the canonical schema
  consumed by both the KPI strip and the trace surface.
* **`GET /api/dispatcher/trace`** is an SSE stream emitting typed
  `span_start` / `span_end` events with monotonic `span_id` and SSE
  `id:` lines for browser-native reconnect.
* **Backend instrumentation slice** (v16.0.0a6) adds `parent_span_id`
  + `trace_id` + `span_context` to every span. Both backends
  (`claude.py`, v17.0.0a2 for `codex.py`) emit child spans for the
  model's own tool use.
* **Waterfall renderer** (v17.0.0a1) at `GET /dispatcher` consumes
  the parent / child stream and renders a true tree. v18.0.0a2
  added a hover / focus tooltip surfacing span attributes.

## 22. Inter-project network graph (v10.0.0a7 → v13.0.0a4)

A live graph of project-to-project MCP calls, separate from the
manifest-derived dependency graph in §18:

* **`MCPCallLog` ring buffer** (v10.0.0a7) records every Harbormaster
  MCP call with caller / target / tool / window. The
  `X-Caller-Project` header propagated from v11.0.0a1 lets a calling
  project identify itself.
* **`network_store.py` SQLite-backed log** (v11.0.0a1) replaces the
  pure ring buffer so the graph survives restarts.
* **`GET /network`** renders the graph with a vendored Cytoscape
  build (373 KB, lives in `ui/static/`).
* **`GET /api/network/stats?window=…`** (v11.0.0a6) is the aggregate
  endpoint used by the chat-list view + dashboard panels.
* **Filters + URL state** (v13.0.0a4) — host / project / tool / window
  filters survive reload via URL state; chat-list ↔ graph view
  toggle is localStorage-backed (v10.0.0a8).

## 23. Memories editor (v10.0.0a5 → v15.0.0a1)

The UI surfaces per-project memory files for read + edit:

* **Allowlist** is intentionally narrow: per-project `CLAUDE.md` plus
  `.serena/memories/*.md`. Anything else is read-only.
* **Atomic write-back** via `PUT` / `POST` (v10.0.0a6).
* **`memory_revisions.db`** (v11.0.0a2) keeps the last 20 revisions
  per file. Editor `History` toggle exposes them; v12.0.0a4 adds
  `GET /api/memory/diff` for unified-diff viewing; v14.0.0a3 surfaces
  side-by-side HtmlDiff.
* **Sanitised markdown** (v11.0.0a3) — `markdown-it-py` for parsing,
  `bleach` for sanitisation, 300 ms debounce live preview.
* **Cmd+Z undo / redo** (v14.0.0a5) — persistent undo cursor lifted to
  v15.0.0a1's tag UX cluster.
* **Tag chip editor + AND/OR filter** (v15.0.0a1) — block-list YAML
  fronts the chip UI.

## 24. Plugins (v2.0)

The plugin system lifted from "post-v2" to first-class in v2.0. A
plugin contributes additional MCP tools and (optionally) UI surfaces.

* `plugins list` CLI (v2.0.1) enumerates discovered plugins.
* Cross-host plugin discovery via SSH (v14.0.0a6) lets the dashboard
  see what's installed remotely.
* Concurrent multi-host plugin discovery (v15.0.0a2) parallelises the
  discovery scan; cross-host config diff lives alongside it.

## 25. Backend protocol + Codex parity (v2.0 → v17.0.0a2)

The backend abstraction is a Python `Protocol` lifted to
`backends/base.py`. Two first-party backends ship in-tree:

| Backend | Token usage | Tool-use sub-spans |
|---|---|---|
| `claude` (v1.0) | Real, in SSE `usage` (v11.0.0a5; was approximate v9.0.0a5–v11.0.0a4) | Yes (v16.0.0a6 backend slice) |
| `codex` (v2.0) | Real (v12.0.0a1) | Yes (v17.0.0a2) |

Symbol re-export pattern (v12.0.0a1): `StreamUsage` + `_StreamWithUsage`
lifted to `base.py`, re-exported from `claude.py` so existing tests +
external callers continue importing from the old location.

## 26. Budget triad (v14.0.0a4 + v15.0.0a4 + v16.0.0a5)

Three independent daily call-budget axes; the tightest cap wins per
incoming MCP call.

| Axis | Config | Endpoint | Version |
|---|---|---|---|
| Per-host | `[hosts.<host>] daily_call_budget = N` | `GET /api/hosts/budget` | v14.0.0a4 |
| Per-tool | `[budget] daily_call_budget_per_tool = { … }` | `GET /api/tools/budget` | v15.0.0a4 |
| Per-project (per host) | `[hosts.<host>.projects.<project>] daily_call_budget = N` | `GET /api/projects/budget?host=…` | v16.0.0a5 |

The dashboard KPI strip surfaces today's headroom per axis plus the
tightest cap. v17.0.0a4 added a hover tooltip on the tightest-cap KPI.

## 27. App shell + light/dark theme (v8 → v19.0.0a1)

The app shell evolved across four majors:

* **v8.0.0a5–a6** — KPI strip atop dashboard, left navigation sidebar
  with grouped projects + pinned. HTMX dropped (a7), semantic OKLCH
  colour tokens added.
* **v9.0.0a1** — Tailwind v4 vendored at wheel-build time
  (`build_tailwind_css.py`); the wheel ships with the minified output.
* **v9.0.0a6** — Sidebar polish (archived / rail-collapse / host
  filter); Cmd-K palette dynamic-action.
* **v10.0.0a3** — Full app-shell layout with fixed topbar / sidebar.
* **v12.0.0a7** — Light-mode toggle (auto / light / dark); no flash
  on reload via early-applied `data-theme` attribute.
* **v15.0.0a6** — Dashboard tour wizard.
* **v19.0.0a1** — Three-column shell rewrite: four-landmark CSS grid
  (`hm-topbar`, `hm-sidebar`, `hm-main`, `inspector`), inspector
  collapse via in-pane button with localStorage persistence. v10
  fixed-footer + v9 mobile-hamburger / rail-collapse retired in
  favour of the inspector-collapse model. Topbar nav links retired —
  Cmd-K palette is the single navigation surface.

## 28. Pre-commit hooks + config doc parity (v15.0.0a5 + v16.0.0a2)

Two repo-local hooks ship in `.pre-commit-config.yaml`:

* **`harbormaster-config-check`** runs `harbormaster-mcp config check`
  against `examples/harbormaster.toml`; fails the commit on any
  schema error.
* **`harbormaster-config-doc-parity`** fails the commit if a Pydantic
  field is added to `src/harbormaster/config.py` without a matching
  mention in `docs/operator-config-reference.md`. On failure it emits
  a copy-paste-ready markdown stanza naming the field, type, and
  default — paste verbatim into the reference.

`pre-commit` ships in `[dev]` (v16.0.0a2); `bash
scripts/post_sync_install_hooks.sh` wires the hook into
`.git/hooks/pre-commit`.

## 29. SSE auth + heartbeat tuning (v11.0.0a7 + v12.0.0a6)

* **Cookie-backed bearer for SSE** (v12.0.0a6) — UI doesn't have to
  pass `Authorization:` from JS; the cookie is set on initial token
  exchange.
* **Per-surface heartbeat tuning** (v11.0.0a7) — defaults are 5 s
  streaming / 30 s network / 10 s trace. Configurable via
  `heartbeat_interval_streaming_s`, `heartbeat_interval_network_s`,
  `heartbeat_interval_trace_s` top-level keys.

---

# Part C — v19.0 Workspace Revamp

Sections 30–34 cover the v19.0 sprint, which retired the v8-era
single-column-with-sidebar layout in favour of a multi-pane workspace
borrowed in spirit from VSCode / Postman / Linear.

## 30. Three-column workspace shell (v19.0.0a1)

`src/harbormaster/ui/templates/base.html` was rewritten around a
four-landmark CSS grid:

```
┌─ topbar (h-12, fixed, full-width) ────────────────────┐
├──────────┬──────────────────────────┬─────────────────┤
│ sidebar  │ main                      │ inspector      │
│ (240px)  │ (1fr, scroll-y)           │ (320px,        │
│ fixed    │                           │  collapsible)  │
└──────────┴──────────────────────────┴─────────────────┘
```

* **Topbar** (`#hm-topbar`) — `⚓ Harbormaster v<version>` brand-mark on
  the left, `{% block page_title %}` centred, Cmd-K hint + theme
  toggle + auth-state lock icon on the right. `position: fixed; top: 0`.
* **Sidebar** (`#hm-sidebar`, `aside`) — extracted to
  `_partials/_sidebar.html` so every page picks it up via
  `{% block sidebar %}{% include "_partials/_sidebar.html" %}{% endblock %}`.
  Contents: `all hosts ▾` filter, `Filter projects…` text input,
  `RECENTLY ASKED`, language groups (`GO`, `JAVASCRIPT`, `PHP`, …)
  with `★`-pinned indicators per project. Independent
  `overflow-y-auto`.
* **Main** (`#hm-main`, `main`) — `{% block content %}` lives here.
  Independent `overflow-y-auto`. The page-specific layout (single column
  vs card grid vs split pane) is the page template's choice; the shell
  is unopinionated.
* **Inspector** (`#inspector`, `aside`) — `{% block inspector %}` lives
  here. Independent `overflow-y-auto`. Collapse via in-pane `«` button
  flips the grid columns to `240px 1fr 0` and persists to
  `localStorage.hm-inspector-collapsed`. Below 1280 px the inspector
  auto-collapses (v20 a6 will replace this with a proper drawer
  pattern below 1024 px).

The four landmarks each carry a stable HTML `id` so e2e tests + future
CSS hooks can reference them without scraping deep selectors.

The Alpine factory `appShell()` owns inspector collapse state +
listeners; it lives inline in `base.html` to keep the shell self-
contained.

## 31. Tab system on `/projects/<name>` (v19.0.0a2 + v19.0.0a8)

The project page got five tabs in the main pane:

| # | Tab            | Source                                  |
|---|----------------|-----------------------------------------|
| 1 | Overview       | Existing project header + status block  |
| 2 | Memories       | New split-pane editor (v19.0.0a8/a9)    |
| 3 | Trajectories   | Relocated `trajectoryList` component    |
| 4 | Q&A History    | Project-scoped recall (v19.0.0a5 stub)  |
| 5 | Settings       | Read-only metadata grid (v20.0.0a3 will edit) |

Mechanics:

* Tab strip uses the v8.0.0a2 `_state_badge`-adjacent visual language
  (active tab gets `border-accent` underline, inactive tabs get
  `border-transparent`). Stable container `id="hm-project-tabs"`.
* **URL-hash persistence**: `#tab=memories` survives reload via
  `restoreFromHash` (init) + `replaceState` (on click — keeps the
  back button bound to navigation, not tab toggling).
* **Keyboard shortcuts `1`..`5`** map to tab indices. The handler
  bails when the focused element is `INPUT`/`TEXTAREA`/`contentEditable`,
  or any modifier key is held.
* **A11y**: every tab button carries
  `aria-label="<label> tab (shortcut <N>)"` so the audit picks up an
  accessible name even though the visible label is `x-text`-injected.

The Alpine factory `projectTabs()` is mounted on the parent `<section>`
of the tab strip — **not** on the same element that owns
`x-show`/`x-transition`, because Alpine has known interaction issues
with multi-directive mounts on the same element (cf. memoriesEditor a8
bug below).

## 32. Memories editor (v19.0.0a8 + v19.0.0a9 hotfix)

The Memories tab on `/projects/<name>#tab=memories` ships a working
edit surface that closes the v10.0.0a5/a6 over-report.

### Layout

```
┌─ FILES (200px) ─┬─ source / preview (split) ─────────┐
│ ★ CLAUDE.md     │ Toolbar: Save · Undo · Redo · diff │
│ + new           ├─────────────────┬──────────────────┤
│ <serena memos>  │ raw markdown    │ rendered preview │
│   …             │ textarea        │ (bleach-clean)   │
└─────────────────┴─────────────────┴──────────────────┘
```

### Wiring

* **File list** populates from `GET /api/projects/{name}/memories`
  (v10.0.0a5).
* **Selecting a file** loads `GET /api/projects/{name}/memories/{file}`
  and `GET /api/projects/{name}/memories/{file}/history`.
* **Live preview** re-renders on textarea input, debounced 300 ms,
  via `POST /api/render-markdown` which goes through
  `harbormaster.ui.markdown.render_safe` (bleach allowlist —
  v11.0.0a3, extended in v12.0.0a4 for `<details>`/`<summary>` and
  footnotes).
* **Save** issues `PUT /api/projects/{name}/memories/{file}`; new
  files via `POST` with `{filename, content}`.
* **Diff** dropdown loads
  `GET /api/projects/{name}/memories/{file}/diff?from=<rev>&to=current&format=html`
  — server-side `difflib.HtmlDiff` (v13.0.0a3).
* **Undo / Redo** are local stack semantics over the `select →
  load → edit` cycle. Cmd-Z / Cmd-Shift-Z are wired via
  `@keydown.cmd.z.prevent="undo()"` on the textarea.

### a8 → a9 hotfix lesson

`v19.0.0a8` mounted the editor with
`x-data="memoriesEditor({{ project_name | tojson }})"`. The `tojson`
filter emits a JSON-quoted string (`"harbormaster"`), and inside a
double-quoted attribute value, the inner `"` collided with the
attribute's outer `"` — the HTML parser truncated the value at the
first inner `"`, Alpine mounted with an empty data stack, and the
editor stayed blank. **Verified visually** by the v19 anti-slop
protocol — without the screenshot step this would have shipped as
"working" per the agent's self-report and re-played the v10
over-report.

`v19.0.0a9` switched to `x-data="memoriesEditor('{{ project_name | e }}')"`
(single quotes outside, Jinja `e`-escaped value inside) and moved
`x-data` off the same element as `x-show`/`x-transition` — Alpine has
documented quirks when those directives co-mount.

The same `tojson` anti-pattern was discovered in `trajectoryList` and
queued for `v20.0.0a1`. **The general rule is now codified**: never
use `{{ … | tojson }}` inside a double-quoted HTML attribute. Use
`'{{ … | e }}'` single-quoted instead, or move the value to a
`data-*` attribute that Alpine reads via `$el.dataset`.

## 33. Inspector pane widgets (v19.0.0a3 + v19.0.0a7)

Each page template defines `{% block inspector %}` to populate the
right-hand pane with context-aware widgets:

| Page                          | Inspector widgets                                   |
|-------------------------------|-----------------------------------------------------|
| `/` Dashboard                 | `SUMMARY` (KPI mini-strip) + `RECENT ACTIVITY` (live SSE feed) |
| `/projects/<name>` Overview   | `METADATA` (last commit, language, host, path, serena/CLAUDE.md presence) + `BUDGET (24H)` |
| `/projects/<name>` Trajectories | Filter controls (date range, tool, host)         |
| `/network`                    | `STATS SUMMARY` (1h calls, error rate, by-tool, top-projects) |
| `/dispatcher`                 | `IN-FLIGHT` count + `RECENT TRACES` summary         |
| `/tools/fan-out`              | Minimal context help                                |

The dashboard inspector's `RECENT ACTIVITY` widget (v19.0.0a7) connects
to the existing `GET /api/network/stream` SSE feed (v10.0.0a7):

* **Initial load** via `GET /api/network/events?limit=10` for the
  last 10 entries.
* **Subscribe** via browser-native `EventSource` (cookie-auth,
  v12.0.0a6).
* **Buffer** incoming events; **flush every 1000 ms** to the DOM —
  the throttle prevents jank on bursty MCP traffic.
* **Pulse** `animate-pulse text-accent` on each new event row for
  1500 ms; class clears via `setTimeout`.
* **Cap** at 10 events; the widget also shows a `view all →` link to
  `/network` for the full feed.

The widget cleans up its `EventSource` on `destroy()` (Alpine's
component-removal hook).

## 34. Linear violet OKLCH palette + compact density (v19.0.0a4)

The v8-era cyan accent was replaced with a Linear-styled violet at hue
290. **OKLCH was chosen** because:

* `oklch()` is the only CSS colour space where lightness perception is
  perceptually uniform — lightness `60%` looks equally "medium" across
  hues.
* Tailwind v4's `@theme` block emits OKLCH natively; no PostCSS
  workaround needed.
* Operator-tunable accents in v20+ become a one-line CSS variable
  swap rather than a regenerate-and-rebuild step.

### Token surface

```
Accent:       --color-accent              oklch(78% .13 290)
              --color-accent-strong       oklch(62% .22 290)
Surface:      --color-surface-0..3        oklch(12-22% .005-.010 280)
Border:       --color-border-subtle/-default/-strong
Foreground:   --color-foreground          oklch(96% .005 280)
              --color-foreground-muted    oklch(75% .005 280)
              --color-foreground-dim      oklch(55% .005 280)
Semantic:     --color-success/warning/danger/info  (hue per status)
```

`--color-accent-strong` was bumped from the spec value
`oklch(54% .21 290)` (3.4:1 contrast against `surface-1`) to
`oklch(62% .22 290)` (≥ 4.5:1) when the
`test_dark_mode_pairs_meet_wcag_aa` regression flagged the spec
value. v20.0.0a5 will repeat the audit in **light mode**.

### Compact density pass

359 token + density substitutions across templates (one migration
script committed for traceability:
`scripts/migrate_v19a4_violet_compact.py`):

* `gap-4 → gap-2`, `gap-3 → gap-2`, `gap-2 → gap-1.5`
* `p-4 → p-2.5`, `px-4 → px-3`, `py-4 → py-2.5`, `p-3 → p-2`
* `text-base → text-sm`, secondary text dropped to `text-xs`
* `mb-6 → mb-4`, `mb-3 → mb-2`, `mt-3 → mt-2`
* `rounded-lg → rounded-md`
* Sidebar rows tightened to `h-7` (down from `~h-9` implied by `py-2`)
* Tabs (from v19.0.0a2): `px-3 py-2 → px-2.5 py-1.5`

Compiled `tailwind.css` grew from ~37 KB (v18) to ~42 KB (v19) — the
violet shade scale is defined for future use even though Tailwind v4's
tree-shaker only emits utilities actually referenced by templates.

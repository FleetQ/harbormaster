# Harbormaster Operator Guide

Practical guide for deploying, configuring, hardening, and upgrading
Harbormaster in production. Audience: someone responsible for
running Harbormaster either as a personal Bridge daemon or as part
of a multi-user FleetQ deployment.

If you're just trying it out for the first time, start with the
[README](../README.md) Install section instead.

## Contents

1. [Deployment options](#1-deployment-options)
2. [Configuration reference](#2-configuration-reference)
3. [Authentication & authorization](#3-authentication--authorization)
4. [Network exposure & reverse proxies](#4-network-exposure--reverse-proxies)
5. [Logging & monitoring](#5-logging--monitoring)
6. [Upgrades](#6-upgrades)
7. [Troubleshooting](#7-troubleshooting)
8. [systemd / launchd integration](#8-systemd--launchd-integration)
9. [Daily operator workflows](#9-daily-operator-workflows)
10. [Budgets and rate limits](#10-budgets-and-rate-limits)
11. [The `config check` CLI](#11-the-config-check-cli)
12. [Pre-commit hooks for downstream forks](#12-pre-commit-hooks-for-downstream-forks)
13. [Execution mode & Claude billing pool routing (v26.0.0+)](#13-execution-mode--claude-billing-pool-routing-v2600)

---

## 1. Deployment options

| Mode | When | Install |
|---|---|---|
| **stdio** | Local Claude Code / Desktop integration | `uvx harbormaster-mcp` (or pipx) |
| **HTTP/SSE on loopback** | Local Bridge daemon for FleetQ tunnel | `uvx --prerelease=allow harbormaster-mcp[ui] --transport sse --port 7531` |
| **HTTP/SSE on public bind** | Multi-user / VPS deployment | Loopback-bound + Cloudflare Tunnel / Tailscale Funnel; **never** raw `--host 0.0.0.0` without a token |
| **Docker** | Containerised production | Use the published `harbormaster-mcp` package inside a slim Python image |

`uvx --prerelease=allow harbormaster-mcp` is the fastest path — uvx
manages a per-tool venv automatically. `pipx install --pip-args='--pre'
harbormaster-mcp` works too if you prefer pipx.

For the streaming + Bridge integration features, install with the
`[ui]` and `[fleetq]` extras:

```bash
uvx --prerelease=allow 'harbormaster-mcp[ui,fleetq]' --version
```

## 2. Configuration reference

Config search order (first hit wins):

1. `--config <path>` CLI flag
2. `./.harbormaster.toml` (current working directory)
3. `$XDG_CONFIG_HOME/harbormaster/config.toml` (default
   `~/.config/harbormaster/config.toml`)
4. Built-in defaults

Minimal example (most users):

```toml
[projects]
glob = ["~/htdocs/*"]

[backends.claude]
enabled = true
binary = "claude"
timeout_local = 90
output_word_cap = 800

[hosts.friday]
remote_htdocs = "/home/katsarov/htdocs"
connect_timeout = 10
total_timeout = 120
```

FleetQ Bridge integration:

```toml
[fleetq]
enabled = true
register_as_bridge = true
write_trajectories = true       # opt-in Memory writeback
write_kg = false                # opt-in KG triple writeback (v1.2 phase 2; noisier than trajectories)
kg_max_triples_per_call = 50    # cap per ask_project / delegate_task on dense answers
base_url = "https://app.fleetq.net"
api_token_env = "FLEETQ_API_TOKEN"
heartbeat_interval = 30
```

Set `FLEETQ_API_TOKEN` in the harbormaster process environment to a
Sanctum bearer token with a `team:<uuid>` ability.

Q&A history (v1.2 phase 1) — opt-in semantic recall over prior
ask_project / delegate_task trajectories:

```toml
[history]
enabled = true                         # default false; everything else is a no-op until this is true
embedding_backend = "fastembed"        # "fastembed" (semantic) | "fts5" (lexical only)
fastembed_model = "BAAI/bge-small-en-v1.5"
embedding_dim = 384                    # must match the model's output dim
db_dir = "~/.harbormaster"             # one qa_<host>.db file per host
retain_recent_k = 1000                 # most-recent rows always kept
retain_top_recalled_r = 100            # most-recalled rows kept regardless of age
log_ask_project = true                 # per-tool opt-out flags
log_delegate_task = true
log_fan_out_ask = true
default_top_k = 5                      # recall_qa default if caller omits
default_min_similarity = 0.6           # vec-path filter; ignored on FTS5 fallback
auto_ground = false                    # v1.2 phase 4: prepend top-K recall to ask_project/delegate_task prompts
auto_ground_top_k = 3                  # how many matches to include in the prior-context section
auto_ground_max_chars = 8000           # cap on prepended context (~2k tokens). Lowest-score matches drop first
auto_ground_min_similarity = 0.55      # filter weak matches before they reach the prompt
```

Install the `[history]` extra (`pipx install 'harbormaster-mcp[history]'`)
to get `sqlite-vec` + `fastembed`. Without the extra,
`embedding_backend = "fastembed"` falls back silently to FTS5 / bm25
lexical recall. The fastembed ONNX model (~50MB) downloads on the
first encode call and caches under the user's HuggingFace cache.

Full TOML schema is enforced by Pydantic (`extra = "forbid"`) — typos
fail loudly at startup.

## 3. Authentication & authorization

### MCP HTTP/SSE transport

Always requires a bearer token. The CLI refuses to bind a
non-loopback host (`--host 0.0.0.0`) without one. Set:

```bash
export HARBORMASTER_MCP_TOKEN=$(python -c 'import secrets; print(secrets.token_urlsafe(32))')
harbormaster-mcp --transport sse --host 127.0.0.1 --port 7532
```

Clients send `Authorization: Bearer <token>` on every request.
Missing or wrong tokens get 401.

### Live UI

Loopback-only by default — no auth needed when bound to 127.0.0.1
because the OS itself enforces "same user only." Setting
`HARBORMASTER_UI_TOKEN` enables opt-in bearer auth on loopback too
(useful for shared dev machines):

```bash
export HARBORMASTER_UI_TOKEN=...
harbormaster-ui --host 127.0.0.1 --port 7531
```

Public bind (`--host 0.0.0.0`) **requires** the token — the CLI
exits with code 2 if it's unset.

### FleetQ Bridge

The token in `FLEETQ_API_TOKEN` is the only credential the bridge
process holds. Rotate via standard FleetQ Sanctum token rotation;
restart the bridge process to pick up the new value.

## 4. Network exposure & reverse proxies

The streaming endpoints (`/mcp/{server}` SSE, `/api/v1/bridge/mcp/call`
on the FleetQ side) require **buffering disabled** at every reverse
proxy in the path. nginx 1.5.6+ honours `X-Accel-Buffering: no` on
`proxy_buffering` by default.

See [`architecture-harbormaster.md` §16](architecture-harbormaster.md)
for the full nginx recipe + verification curl.

Common deployment shapes:

- **Cloudflare Tunnel**: passes `X-Accel-Buffering` through. No
  extra config.
- **Tailscale Funnel**: same. No extra config.
- **nginx in front**: add `proxy_buffering off` to the location
  block + `proxy_read_timeout 300s` (tools take 30-90s).
- **Caddy**: by default streams without buffering. Verify with the
  curl in §16.
- **AWS ALB / Cloudflare Load Balancer**: confirm "streaming
  responses" is enabled.

If your stream looks like one big chunk at the end instead of
incremental output, a proxy is buffering. Add `proxy_buffering off`
(or equivalent) to each layer until `event: chunk` lines appear in
real time.

## 5. Logging & monitoring

`--log-format text` (default) is human-readable. `--log-format json`
emits one JSON object per record — pair with `journalctl`/Docker
log drivers.

Useful log lines to watch for:

- `FleetQ bridge registered: session=…` — successful Bridge handshake
- `FleetQ bridge session lost — re-registering` — heartbeat returned
  404, automatic recovery in progress
- `FleetQ memory writeback rejected: HTTP …` — non-fatal, but worth
  alerting on if you depend on Memory persistence

CI-side checks (recommended):

- The `smoke-mcp-streaming` job in this repo's CI verifies the
  daemon's SSE wire shape on every push. Worth replicating in your
  own deployment's CI.
- The gated `smoke-fleetq` job runs against a real FleetQ if you set
  `FLEETQ_SMOKE_ENABLED=true` + `FLEETQ_TEST_BASE_URL` +
  `FLEETQ_TEST_API_TOKEN` repository variable/secrets.

## 6. Upgrades

Each `v*` git tag triggers a PyPI publish via Trusted Publishing
(no API tokens in the repo). Released versions follow `1.0.0aN`
during the alpha phase; `v1.0.0` GA drops the alpha suffix.

To upgrade a uvx-installed daemon:

```bash
# uvx caches per-tool; refresh:
uvx --refresh --prerelease=allow harbormaster-mcp --version
```

Restart the running daemon (systemd / launchd unit; or `kill $PID`
for a foreground run) to pick up the new code.

For pinned production deployments, pin the version explicitly in
your launcher:

```bash
uvx --prerelease=allow harbormaster-mcp@1.0.0a15 --transport sse ...
```

## 7. Troubleshooting

### `event: chunk` lines arrive only at the end

A reverse proxy in the path is buffering. See §4 +
[architecture §16](architecture-harbormaster.md).

### `invalid-publisher` on PyPI tag push

PyPI Trusted Publisher not registered. See `docs/publishing.md`.
Both prod (`pypi.org`) and `testpypi` need the Trusted Publisher
configured before the workflow can succeed.

### FleetQ Bridge stays "Disconnected" in the FleetQ UI

Heartbeat is hitting the FleetQ side but the daemon's session has
been marked stale. Check:

- `FLEETQ_API_TOKEN` is set correctly in the daemon process
  (`systemctl show <unit> --property=Environment`)
- The token has the right team ability
- The daemon's logs show `FleetQ bridge registered: session=…` at
  startup

### `claude -p` exits non-zero with `not authenticated`

The Anthropic seat for that environment isn't set up. `claude
auth` in the relevant context (local user, SSH host, etc.)
to authenticate.

### Streaming chunks stop mid-stream

Most likely the upstream `claude -p` subprocess died or the
configured `total_timeout` was hit. Check the harbormaster log for
`BackendError(code='exit_nonzero')` or `BackendError(code='timeout')`.

## 8. systemd / launchd integration

### systemd unit (Linux)

```ini
# /etc/systemd/system/harbormaster.service
[Unit]
Description=Harbormaster MCP Bridge daemon
After=network-online.target

[Service]
Type=simple
User=harbormaster
Group=harbormaster
EnvironmentFile=/etc/harbormaster/env
ExecStart=/usr/local/bin/uvx --prerelease=allow 'harbormaster-mcp[ui,fleetq]' --transport sse --host 127.0.0.1 --port 7532
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

`/etc/harbormaster/env` (chmod 600):

```
HARBORMASTER_MCP_TOKEN=<32-byte token>
FLEETQ_API_TOKEN=<sanctum token>
```

### launchd (macOS)

```xml
<!-- ~/Library/LaunchAgents/com.harbormaster.bridge.plist -->
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.harbormaster.bridge</string>
  <key>ProgramArguments</key>
  <array>
    <string>/Users/<user>/.local/bin/uvx</string>
    <string>--prerelease=allow</string>
    <string>harbormaster-mcp[ui,fleetq]</string>
    <string>--transport</string><string>sse</string>
    <string>--host</string><string>127.0.0.1</string>
    <string>--port</string><string>7532</string>
  </array>
  <key>EnvironmentVariables</key>
  <dict>
    <key>HARBORMASTER_MCP_TOKEN</key><string>...</string>
    <key>FLEETQ_API_TOKEN</key><string>...</string>
  </dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>/tmp/harbormaster.log</string>
  <key>StandardErrorPath</key><string>/tmp/harbormaster.err</string>
</dict>
</plist>
```

`launchctl load ~/Library/LaunchAgents/com.harbormaster.bridge.plist`.

For a long-running daemon on a MacBook used as a server, see the
"clamshell mode" gotcha — user LaunchAgents don't fire when the
display is closed. Use a root LaunchDaemon under
`/Library/LaunchDaemons/` instead, with the user-context unit
kicked by a system-context "kicker" job.

---

## 9. Daily operator workflows

The web UI (`harbormaster-ui --port 7531`) is the primary daily
surface. Each section below names the URL, the underlying API, and
the alpha that introduced the surface so you can cross-reference
the [CHANGELOG](../CHANGELOG.md) for behaviour changes.

### Run an ask against a single project

`/projects/<name>` → "Ask this project" form (v2.1.0a4). Submits to
`POST /api/ask` with SSE streaming back into the page. The same
form lives inline on every dashboard project card (v3.0.0a7). For
a non-UI run:

```bash
curl -N -X POST http://127.0.0.1:7531/mcp/harbormaster \
  -H "Authorization: Bearer $HARBORMASTER_UI_TOKEN" \
  -H 'Accept: text/event-stream' \
  -H 'Content-Type: application/json' \
  -d '{"method":"tools/call","params":{"name":"ask_project","arguments":{"name":"alpha","question":"summarize"}}}'
```

### Fan out to many projects

Dashboard "Fan-out" form (v2.1.0a5) or `fan_out_ask(...)` MCP tool.
Streams a section per target as each completes; one row per target
with a state badge that flips ready → in-flight → completed →
failed (using the unified `stateBadge` helper, v11.0.0a4 / a-migration
v12.0.0a2).

### Recall prior Q&A

`/recall?q=...` (URL pre-fillable, v4.0.0a2 + v11.0.0a4). Calls
`recall_qa` against the local Q&A history (or `host="all"` for
cross-host aggregation, v2.0 + v3.0.0a4 thread pool). Disabled by
default — set `[history] enabled = true` in your config TOML to
populate the database, then ask a few questions to seed it.

### Browse the inter-project network graph

`/network` (v10.0.0a7). Live SSE-driven graph of MCP calls between
projects. Filter by host / project / tool / window from the toolbar;
toggle graph ↔ chat-list view (v10.0.0a8). Aggregate stats for the
current window are at `GET /api/network/stats?window=…` (v11.0.0a6).

The graph survives daemon restarts — backed by
`~/.harbormaster/network_log.db` (v11.0.0a1).

### Open the dispatcher trace

`/dispatcher` (v9.0.0a3 → v17.0.0a1 renderer). Live waterfall of
in-flight + last-100 completed spans. Click a span to expand
attributes (or hover for the v18.0.0a2 tooltip). Both `claude` and
`codex` backends emit child spans for the model's own tool use.

### Edit a memory file

`/projects/<name>` → memories tab (v10.0.0a5 / a6). Allowlist:
per-project `CLAUDE.md` + `.serena/memories/*.md` only. Toggle
`History` to see the last 20 revisions; pick two and side-by-side
HTML diff renders (v14.0.0a3). Cmd+Z undoes (v14.0.0a5); the chip
editor (v15.0.0a1) manages tags inline.

### Run a pre-flight check on your config

```bash
harbormaster-mcp config check
# or, for a specific file:
harbormaster-mcp config check --config ~/.config/harbormaster/config.toml
```

(See [§11](#11-the-config-check-cli) for output format and exit
codes.)

---

## 10. Budgets and rate limits

Three independent daily call-budget axes; the **tightest cap wins**
per incoming MCP call. All three are opt-in (omit a key → no cap on
that axis).

| Axis | Config TOML | Endpoint | Version |
|---|---|---|---|
| Per-host | `[hosts.<host>] daily_call_budget = 200` | `GET /api/hosts/budget` | v14.0.0a4 |
| Per-tool | `[budget] daily_call_budget_per_tool = { ask_project = 200, … }` | `GET /api/tools/budget` | v15.0.0a4 |
| Per-project | `[hosts.<host>.projects.<project>] daily_call_budget = 50` | `GET /api/projects/budget?host=…` | v16.0.0a5 |

The dashboard KPI strip surfaces today's headroom for each axis plus
the tightest-cap value (with a hover tooltip showing which axis is
the bottleneck — v17.0.0a4).

When a call hits the cap, the daemon returns an MCP error with a
`budget_exceeded` code naming the axis. Reset is at midnight in the
host's local timezone.

---

## 11. The `config check` CLI

`harbormaster-mcp config check` (v14.0.0a2) loads the config the
same way the daemon does, validates against the Pydantic schema,
and prints either:

- a green `OK` summary listing each section + key count, or
- a structured error report with file path, section, key, and the
  Pydantic violation message.

Exit code 0 on OK, 2 on validation failure. Use it as a pre-flight
in your deployment script:

```bash
harbormaster-mcp config check --config /etc/harbormaster/config.toml \
  || { echo "config invalid — refusing to start"; exit 1; }
```

The same check runs in the `harbormaster-config-check` pre-commit
hook against `examples/harbormaster.toml` (v15.0.0a5) so the
example never drifts from the real schema.

---

## 12. Pre-commit hooks for downstream forks

If you fork or extend Harbormaster, install the repo-local hooks
once after `uv sync`:

```bash
uv sync --extra dev
bash scripts/post_sync_install_hooks.sh
```

The hooks (also referenced from the README):

- **`harbormaster-config-check`** — validates `examples/harbormaster.toml`
  on every commit.
- **`harbormaster-config-doc-parity`** — fails the commit if a Pydantic
  field is added to `src/harbormaster/config.py` without a matching
  mention in [`operator-config-reference.md`](operator-config-reference.md).
  On failure the hook emits a paste-ready markdown stanza for the
  field.

Both hooks are fast (<1 s each) and run on every `git commit`.

---

## 13. Execution mode & Claude billing pool routing (v26.0.0+)

Starting **2026-06-15**, Anthropic separates programmatic Claude usage
(Agent SDK, `claude -p`, third-party apps authenticating through the
Agent SDK) from the Max plan's interactive usage pool. Programmatic
calls draw from a dedicated **\$200/mo credit pool** (Max 20x; \$100
for Max 5x; \$20 for Pro) at full API rates, with no rollover. See the
research synthesis at
[`../claudedocs/research_anthropic_credit_policy_2026-05-14.md`](../claudedocs/research_anthropic_credit_policy_2026-05-14.md).

Harbormaster v26.0.0 introduces an **instruction-mode** path that
returns a markdown packet to the calling MCP client (typically your
interactive `claude` TUI) instead of spawning `claude -p` server-side.
The calling assistant executes the packet's prompt via its own `Agent`
/ `Task` subagent — those API calls inherit the parent session's auth
context and bill against the **interactive subscription pool**, not
the credit pool.

### 13.1 Default behaviour

`[delegate] execution_mode = "instruction"` is the default. No
configuration change needed for typical interactive workflows:

1. Operator runs `claude` from a project dir.
2. Inside the TUI, the assistant calls `mcp__harbormaster__delegate_task(...)`.
3. Harbormaster returns a `HARBORMASTER_INSTRUCTION_V1` markdown packet.
4. The assistant spawns `Agent(prompt=..., cwd=...)` per the packet.
5. After the Agent returns, the assistant calls
   `mcp__harbormaster__record_delegation_result(job_id=..., status=...,
   output=..., duration_ms=..., tokens_used=...)`.
6. The JobStore row transitions to `completed` / `failed`; SSE on
   `/jobs` and FleetQ Bridge subscribers fire identically to the
   v22-v25 subprocess path.

Every step happens inside one interactive Claude Code session — the
subprocess-spawning path is bypassed entirely.

### 13.2 Verifying you're on the subscription pool

The cost-routing assumption relies on two preconditions:

1. **Your interactive `claude` is authenticated via subscription
   OAuth, not an API key.**
   Check: `claude doctor` shows `auth=subscription` (Pro/Max). If it
   shows `auth=api-key`, the parent session — and every Agent it
   spawns — bills against the API account, not the subscription pool.
2. **No `ANTHROPIC_API_KEY` env var leaks into Harbormaster's
   subprocess context.** Even in instruction mode, the Harbormaster
   process inherits the operator's env; an `ANTHROPIC_API_KEY`
   leaking through can re-shape behaviour for any future subprocess
   path.

The safest pattern:

```bash
# Generate a long-lived subscription OAuth token (one-time):
claude setup-token
# → outputs a token of the form sk-ant-oat01-...

# Export it on every Harbormaster invocation:
export CLAUDE_CODE_OAUTH_TOKEN=sk-ant-oat01-...

# CRITICAL: ensure no API key shadows the subscription auth:
unset ANTHROPIC_API_KEY
```

Drop those two lines into your `~/.zshrc` / shell init so every shell
that launches `claude` or `harbormaster-mcp` honours the same
contract.

**Known footgun**: GitHub issue
[#37686](https://github.com/anthropics/claude-code/issues/37686)
documents an operator who got a **\$1,800 unexpected API bill in two
days** because a stale `ANTHROPIC_API_KEY` was set in their cron
environment. The variable silently won over the subscription OAuth —
no warning, no log line. Audit your shell init files before relying
on v26's cost routing.

### 13.3 When to opt back to subprocess mode

The instruction-mode path requires an interactive caller — there must
be a calling assistant to receive the packet and execute the Agent.
For these scenarios, set `[delegate] execution_mode = "subprocess"`:

- **Unattended cron jobs / overnight pipelines** with no human-facing
  TUI. The subprocess path spawns `claude -p` directly and bills
  against the credit pool.
- **CI / GitHub Actions** workflows triggering delegate work without a
  human in the loop.
- **SSH cross-host delegation**. Harbormaster auto-falls-back to
  subprocess for any non-local target regardless of this setting
  (the calling assistant has no PTY to the remote host) — explicit
  config not needed but harmless.

Mixed setups are supported: keep `execution_mode = "instruction"`
globally and trust the SSH auto-fallback for the few cross-host calls.

### 13.4 Orphan sweep

Instruction-mode rows wait in status `awaiting_caller` until the
calling assistant invokes `record_delegation_result`. If the caller
crashes mid-Agent or never reports back, the row would otherwise
linger forever. Harbormaster sweeps stale `awaiting_caller` rows to
`failed` with error `caller_never_recorded_result` after
`[delegate] awaiting_caller_timeout_seconds` (default 3600 = 1 h).
Set to `0` to disable the sweep. The sweep runs once at subsystem
boot AND opportunistically inside every `record_delegation_result`
invocation, so no dedicated heartbeat thread is needed.

### 13.5 Observing the routing in `/jobs`

The UI surfaces per-row provenance via the `Mode` column
(`instr` / `subproc`) and per-row `Tokens` reported by the caller
(NULL when no value was passed). Use these for sanity-checking your
routing: if interactive use suddenly shows `subproc` rows, an env
override likely flipped the dispatch.

### 13.6 Migration from v25 and earlier

No data migration is required — Harbormaster applies idempotent
`ALTER TABLE` migrations on first boot of the new code, adding the
`execution_mode` (default `'subprocess'`), `tokens_used` (NULL),
`rendered_prompt` (NULL), and `batch_id` (NULL) columns. Existing
rows preserve their actual provenance under the new schema.

---

For architectural details (module layout, data flow, threading
model), see [`architecture-harbormaster.md`](architecture-harbormaster.md).
For the long-form design rationale, see
[`design-harbormaster.md`](design-harbormaster.md).
For the canonical TOML schema reference, see
[`operator-config-reference.md`](operator-config-reference.md).
For the user-facing release history, see
[`../CHANGELOG.md`](../CHANGELOG.md).

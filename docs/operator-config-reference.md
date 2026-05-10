# Harbormaster Operator Config Reference

**Canonical reference for every Harbormaster TOML config section.**
Closes the v12 retro item ("operator-facing config docs scattered
across READMEs, design docs, and per-feature retros").

## Loading order

Harbormaster looks for config files in this order — first match wins:

1. `./.harbormaster.toml` in the current working directory
   (per-project override — useful when you want different defaults
   while running `harbormaster-mcp` from inside a project).
2. `$XDG_CONFIG_HOME/harbormaster/config.toml`
   (or `~/.config/harbormaster/config.toml` when `XDG_CONFIG_HOME`
   is unset).

If no config file is found, the package boots with all defaults — it
auto-discovers projects under `~/htdocs/*` and emits no warnings.

Schema validation is strict: any unknown key in a documented section
raises a `pydantic.ValidationError` at startup, with a pointer to
the offending key. There is no silent-drop path.

## Table of contents

- [`[projects]`](#projects)
- [`[ignore]`](#ignore)
- [`[backends.<name>]`](#backendsname)
- [`[hosts.<label>]`](#hostslabel)
- [`[server]`](#server)
- [`[storage]`](#storage)
- [`[fleetq]`](#fleetq)
- [`[history]`](#history)
- [`[plugins]`](#plugins)
- [`[retention]`](#retention)
- [`[budget]`](#budget)
- [Top-level keys](#top-level-keys)
- [Worked example](#worked-example)

---

## `[projects]`

Source of truth for which directories appear in `list_projects()` and
the dashboard project grid.

| Key              | Type        | Default              | Notes |
|------------------|-------------|----------------------|-------|
| `glob`           | `list[str]` | `["~/htdocs/*"]`     | One or more shell-style glob patterns. Matched against the filesystem at process start; non-existent paths are silently skipped. |
| `exclude`        | `list[str]` | `[]`                 | gitignore-style component names. A project is hidden if any path component matches a pattern. |
| `require_marker` | `bool`      | `false`              | When `true`, only directories containing a `.git/`, `pyproject.toml`, `package.json`, etc. are surfaced. |

```toml
[projects]
glob = ["~/code/*", "~/work/*"]
exclude = ["**/node_modules/**", "**/vendor/**"]
require_marker = true
```

## `[ignore]`

Project-name globs (v10.0.0a4) — distinct from `[projects].exclude`
which targets path components.

| Key        | Type        | Default | Notes |
|------------|-------------|---------|-------|
| `patterns` | `list[str]` | `[]`    | `fnmatch.fnmatchcase` patterns matched against project basename + full path. A project is hidden when it matches EITHER `[projects].exclude` or `[ignore].patterns`. |

```toml
[ignore]
patterns = ["*-archive", "*-ui", "experimental-*"]
```

## `[backends.<name>]`

The named backend definition. The default `[backends.claude]` block
is created automatically when no `[backends.*]` table is present.
Add `[backends.codex]` (or any name) to register additional backends.

| Key              | Type        | Default              | Notes |
|------------------|-------------|----------------------|-------|
| `enabled`        | `bool`      | `true`               | Toggle without deleting the block. |
| `binary`         | `str`       | `"claude"`           | Executable on PATH. |
| `extra_args`     | `list[str]` | `["-p"]`             | Always passed before the prompt. |
| `timeout_local`  | `int` (s)   | `60`                 | Local invocation budget. |
| `timeout_remote` | `int` (s)   | `120`                | SSH invocation budget — needs to cover SSH handshake + remote start. |
| `output_word_cap`| `int`       | `800`                | Hard cap on response length post-truncation; protects context-window budgets in calling agents. |

```toml
[backends.claude]
binary = "claude"
extra_args = ["-p", "--model", "claude-opus-4-5"]
output_word_cap = 1200

[backends.codex]
binary = "codex"
extra_args = []
timeout_local = 90
```

## `[hosts.<label>]`

Each `[hosts.<label>]` block registers an SSH host that
project-targeting tools can target via `host="<label>"`.

| Key               | Type      | Default       | Notes |
|-------------------|-----------|---------------|-------|
| `ssh_host`        | `str`     | required      | Hostname or `~/.ssh/config` Host alias. |
| `remote_htdocs`   | `str`     | `"~/htdocs"`  | Where the remote `claude` should `cd`. |
| `backend`         | `str`     | `"claude"`    | Backend name to invoke remotely. Must exist in `[backends.<name>]`. |
| `connect_timeout` | `int` (s) | `10`          | Passed to `ssh -o ConnectTimeout`. |
| `total_timeout`   | `int` (s) | `120`         | Outer wall-clock budget (kills the remote command after N seconds). |
| `daily_call_budget` | `int`   | _none_        | v14.0.0a4: optional soft cap on the number of MCP calls routed to this host per 24h. Surfaced via `GET /api/hosts/budget` and the dashboard KPI strip. `None` (default) means no budget tracked. |

```toml
[hosts.friday]
ssh_host = "katsarov-server.local"

[hosts.hetzner-1]
ssh_host = "hetzner-1.example.com"
remote_htdocs = "/var/www"
backend = "codex"
connect_timeout = 20
```

## `[server]`

Process-wide knobs shared by both `harbormaster-mcp` and `harbormaster-ui`.

| Key                                   | Type      | Default | Range / notes |
|---------------------------------------|-----------|---------|---------------|
| `ui_port`                             | `int`     | `7531`  | 1..65535. Bound by `harbormaster-ui` when `--port` is omitted. |
| `mcp_http_port`                       | `int`     | `7532`  | 1..65535. Used when `harbormaster-mcp --transport streamable-http`. |
| `log_level`                           | `str`     | `"info"`| One of `debug, info, warning, error, critical`. |
| `trajectory_retention_days`           | `int`     | `90`    | > 0. How long the dashboard's trajectory view keeps Q&A entries. |
| `heartbeat_interval_streaming_s`      | `float`   | `5.0`   | > 0. SSE heartbeat for `ask`/`delegate`/`fan_out` streams. |
| `heartbeat_interval_network_s`        | `float`   | `30.0`  | > 0. SSE heartbeat for `/api/network/stream`. |
| `heartbeat_interval_trace_s`          | `float`   | `10.0`  | > 0. SSE heartbeat for `/api/dispatcher/trace/stream`. |

```toml
[server]
ui_port = 8443
mcp_http_port = 8444
log_level = "debug"
heartbeat_interval_streaming_s = 3.0
```

## `[storage]`

Where Harbormaster persists its state.

| Key            | Type   | Default                                              | Notes |
|----------------|--------|------------------------------------------------------|-------|
| `db_path`      | `str`  | `"~/.local/share/harbormaster/harbormaster.db"`      | SQLite file used by the persistent metadata store. Tilde / `$VAR` expanded at load. |
| `enable_dedup` | `bool` | `false`                                              | When `true`, the persistent store dedups Q&A by question hash. |

## `[fleetq]`

FleetQ Bridge integration. All keys are opt-in; default keeps
Harbormaster fully standalone.

| Key                      | Type      | Default                          | Notes |
|--------------------------|-----------|----------------------------------|-------|
| `enabled`                | `bool`    | `false`                          | Master toggle. Must be `true` for any FleetQ writeback. |
| `base_url`               | `str`     | `"https://app.fleetq.net"`       | FleetQ HTTP API root. |
| `api_token_env`          | `str`     | `"FLEETQ_API_TOKEN"`             | Name of the env var holding the API token. |
| `write_trajectories`     | `bool`    | `true`                           | Per-feature gate (a16). |
| `write_kg`               | `bool`    | `false`                          | Per-feature gate. KnowledgeGraph triple writeback. |
| `kg_max_triples_per_call`| `int`     | `50`                             | > 0. Hard cap on triples written per Q&A. |
| `kg_extractor`           | `enum`    | `"heuristic"`                    | One of `heuristic, llm, both`. |
| `kg_llm_max_triples`     | `int`     | `20`                             | > 0. Cap when the LLM extractor is active. |
| `publish_a2a_cards`      | `bool`    | `false`                          | Publish A2A v0.3 agent cards per project. |
| `register_as_bridge`     | `bool`    | `false`                          | Register this Harbormaster as a Bridge with FleetQ. |
| `heartbeat_interval`     | `int` (s) | `30`                             | > 0. Bridge heartbeat cadence. |
| `dispatcher_max_workers` | `int`     | `1`                              | 1..16. >1 enables a bounded ThreadPoolExecutor for parallel `agent.request` dispatch. |
| `dispatcher_unsafe_tools`| `list[str]`| `[]`                            | Per-tool deny list — these always run on the single-worker path even when `dispatcher_max_workers > 1`. |

## `[history]`

Q&A history + sqlite-vec recall.

| Key                          | Type      | Default                          | Notes |
|------------------------------|-----------|----------------------------------|-------|
| `enabled`                    | `bool`    | `false`                          | Master toggle. |
| `embedding_backend`          | `enum`    | `"fastembed"`                    | One of `fastembed, fts5`. |
| `fastembed_model`            | `str`     | `"BAAI/bge-small-en-v1.5"`       | When `fastembed`. |
| `embedding_dim`              | `int`     | `384`                            | > 0. Must match the chosen model. |
| `db_dir`                     | `str`     | `"~/.harbormaster"`              | SQLite DB directory. Expanded. |
| `retain_recent_k`            | `int`     | `1000`                           | > 0. Window of most-recent rows kept. |
| `retain_top_recalled_r`      | `int`     | `100`                            | > 0. Most-recalled rows kept regardless of age. |
| `log_ask_project`            | `bool`    | `true`                           | Per-tool gate. |
| `log_delegate_task`          | `bool`    | `true`                           | Per-tool gate. |
| `log_fan_out_ask`            | `bool`    | `true`                           | Per-tool gate. |
| `default_top_k`              | `int`     | `5`                              | > 0. Default `recall_qa` `top_k`. |
| `default_min_similarity`     | `float`   | `0.6`                            | 0.0..1.0. |
| `auto_ground`                | `bool`    | `false`                          | Auto-prepend recall results to prompts. |
| `auto_ground_top_k`          | `int`     | `3`                              | > 0. |
| `auto_ground_max_chars`      | `int`     | `8000`                           | > 0. |
| `auto_ground_min_similarity` | `float`   | `0.55`                           | 0.0..1.0. |
| `parallel_recall`            | `bool`    | `false`                          | Parallelize `host="all"` recall (v3.0.0a4). |
| `parallel_recall_max_workers`| `int`     | `4`                              | 1..32. |
| `auto_reembed_on_drift`      | `bool`    | `false`                          | v4.0.0a5. |
| `optimistic_stale_seconds`   | `int` (s) | `5`                              | 1..600. v6.0.0a2 trajectory stale tier. |

## `[plugins]`

Entry-point plugin discovery (v2.0.0a4). Deny-by-default — even when
enabled, only distributions in `allow` load.

| Key       | Type        | Default | Notes |
|-----------|-------------|---------|-------|
| `enabled` | `bool`      | `false` | Master toggle. |
| `allow`   | `list[str]` | `[]`    | Distribution names. Empty list = nothing loads even when enabled. |

```toml
[plugins]
enabled = true
allow = ["harbormaster-plugin-jira", "internal-tooling-plugin"]
```

## `[retention]`

v12.0.0a3. Operator-tunable retention caps for the UI's persistent
stores. Defaults preserve v11 behavior byte-for-byte.

| Key                          | Type      | Default | Notes |
|------------------------------|-----------|---------|-------|
| `network_log_max_rows`       | `int`     | `5000`  | > 0. Cap on `mcp_calls` rows in `~/.harbormaster/network_log.db`. |
| `memory_revisions_per_file`  | `int`     | `20`    | > 0. Cap on revisions per (project, file) pair. |
| `qa_log_recent_k`            | `int`     | `null`  | When set, overrides `[history].retain_recent_k` for QAStore.prune. |
| `qa_log_top_recalled_r`      | `int`     | `null`  | When set, overrides `[history].retain_top_recalled_r`. |

## `[budget]`

v15.0.0a4. Per-tool soft call budgets — operator-side warning surface,
not enforcement. Counterpart to `[hosts.<label>].daily_call_budget`
which tracks per-host call volume; `[budget]` tracks per-tool volume.
Surfaced via `GET /api/tools/budget` and on the dashboard host-budget
KPI cell (hover expands to show the per-tool breakdown).

| Key                              | Type            | Default | Notes |
|----------------------------------|-----------------|---------|-------|
| `daily_call_budget_per_tool`     | `dict[str,int]` | `{}`    | Map of `tool_name → budget` (calls per 24h). All values must be > 0. Tools NOT listed have no budget tracked. Empty (default) means no per-tool budgets. Example: `daily_call_budget_per_tool = { ask_project = 1000, fan_out_ask = 100 }`. |

## Top-level keys

These live at the root of the TOML file (no section header).

| Key                     | Type             | Default   | Notes |
|-------------------------|------------------|-----------|-------|
| `default_backend`       | `str`            | `"claude"`| Falls through when no per-project override matches. |
| `backends_for_project`  | `dict[str, str]` | `{}`      | Per-project override map: `{ "alpha" = "codex" }`. Values must be backend names that exist in `[backends.<name>]`. |

## Worked example

A representative full-featured config:

```toml
default_backend = "claude"
backends_for_project = { "rust-experimental" = "codex" }

[projects]
glob = ["~/code/*", "~/work/*"]
exclude = ["**/node_modules/**", "**/vendor/**"]
require_marker = true

[ignore]
patterns = ["*-archive"]

[backends.claude]
binary = "claude"
extra_args = ["-p", "--model", "claude-opus-4-5"]
output_word_cap = 1200

[backends.codex]
binary = "codex"
extra_args = []
timeout_local = 90

[hosts.friday]
ssh_host = "katsarov-server.local"

[hosts.hetzner-1]
ssh_host = "hetzner-1.example.com"
remote_htdocs = "/var/www"
backend = "codex"

[server]
ui_port = 8443
log_level = "info"

[fleetq]
enabled = true
api_token_env = "FLEETQ_API_TOKEN"
write_kg = true
kg_extractor = "both"
dispatcher_max_workers = 4
dispatcher_unsafe_tools = ["legacy_export"]

[history]
enabled = true
auto_ground = true
auto_ground_top_k = 3
parallel_recall = true

[plugins]
enabled = true
allow = ["harbormaster-plugin-jira"]

[retention]
network_log_max_rows = 25000
memory_revisions_per_file = 50
```

This config registers two backends, two hosts, enables FleetQ
writeback (with KG triples + parallel dispatcher), turns on Q&A
history with auto-grounding, allowlists one plugin, and bumps the
network-log retention to 25k rows.

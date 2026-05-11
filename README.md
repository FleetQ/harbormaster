# Harbormaster

> One MCP server, many projects, one operator console. Local + SSH + observability + budgets — without changing directory.

[![PyPI](https://img.shields.io/pypi/v/harbormaster-mcp.svg?label=harbormaster-mcp)](https://pypi.org/project/harbormaster-mcp/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Status](https://img.shields.io/badge/status-stable-green.svg)](#versioning)

Harbormaster is an MCP server that routes Q&A and delegations across every
project on your machine — and across SSH-reachable hosts — without making you
`cd` between them. Each target project's subagent loads its own `CLAUDE.md` /
Serena memories, answers, and returns a summary back to the calling
session.

It also ships a local web dashboard for the operator: a project grid with
KPIs, an inter-project network graph, a live dispatcher trace waterfall,
a memory editor for `CLAUDE.md` and `.serena/memories/*.md`, multi-axis
budgets (per-host, per-tool, per-project), and a light/dark theme.

> Part of the [FleetQ](https://fleetq.net) ecosystem. Standalone OSS works
> fully without FleetQ; FleetQ Bridge integration is purely additive.

---

## What it does

You work across many projects, each with its own `CLAUDE.md` and Serena
memories. Switching cwd loses context. Harbormaster lets one Claude Code
(or Codex) session ask any project a question without changing directory —
the project's subagent loads its own memory, answers, and returns a summary.

Eight MCP tools cover the day-to-day flow: list projects and hosts, inspect
project status, ask a single project, fan out to many, recall prior Q&A,
walk the inter-project dependency graph. Optional SSH fan-out targets
remote VPS hosts. Optional FleetQ adapter exposes Harbormaster as a
first-class Bridge daemon (Platform Tool, A2A Agent Cards, federated
KnowledgeGraph).

The companion web UI turns the same MCP server into a local operator
console: dashboards, trace waterfall, network graph, memory editor.

---

## Quick start

Install with the `[ui]` extra so you also get the operator dashboard:

```bash
uvx --prerelease=allow 'harbormaster-mcp[ui]' --version
# or with pipx:
pipx install --pip-args='--pre' 'harbormaster-mcp[ui]'
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

Run the operator UI alongside (separate process — both read the same
TOML config so projects discovered by one are visible to the other):

```bash
export HARBORMASTER_UI_TOKEN=$(python -c 'import secrets; print(secrets.token_urlsafe(32))')
harbormaster-ui --port 7531
# then open http://127.0.0.1:7531/ — paste the token at the prompt
```

Zero-config by default: Harbormaster auto-discovers projects under
`~/htdocs/*` if it exists. For any other layout, see [Configuration](#configuration).

---

## Tools

Eight MCP tools, all optionally targetable at a remote host via `host="<label>"`.

| Tool | Purpose | Cost |
|---|---|---|
| `list_projects(host=None)` | Enumerate configured projects (local) or remote dir listing (SSH). | ~50 ms / ~1 s |
| `list_hosts()` | Configured `[hosts]` plus `~/.ssh/config` Host aliases. | ~5 ms |
| `project_status(name, host=None)` | Git log, Serena memory list, log tails. | ~200 ms / ~2 s |
| `ask_project(name, question, max_turns=5, host=None)` | Spawn `claude -p` (or configured backend) in project cwd, return ≤ 800-word summary. | ~30 s / ~90 s |
| `delegate_task(name, task, deliverable, allow_writes=False, host=None)` | Read-only delegation (writes fail closed by default). | ~60 s / ~90 s |
| `fan_out_ask(question, project_filter=None, host_filter=None, max_concurrency=5, max_turns=3)` | Parallel multi-project Q&A; one section per target. | ~`max_turns × backend_time × ⌈targets / max_concurrency⌉` |
| `recall_qa(question, top_k=5, host=None, project=None, min_similarity=0.6)` | Semantic recall over prior Q&A answers. Opt-in via `[history] enabled = true`. | ~50 ms (FTS5) / ~150 ms (vec, after warm-up) |
| `project_graph(format="json", include_dev_deps=False, transitive=False)` | Cross-project dependency graph from manifest parsing. Returns nodes + edges + optional Mermaid markup. | ~100 ms / ~10 ms cached |

Full design notes for each tool live in [`docs/architecture-harbormaster.md`](docs/architecture-harbormaster.md).

---

## UI overview

The companion dashboard (`harbormaster-ui --port 7531`) is a local-first
operator console. All surfaces speak the same SSE event stream that powers
the MCP transport, so what you see in the UI matches what your MCP clients
see.

### Workspace shell (v19+)

Every page renders inside a fixed three-column workspace borrowed in spirit
from VSCode / Postman / Linear:

```
┌─ topbar (h-12, fixed) ────────────────────────────────┐
├──────────┬──────────────────────────┬─────────────────┤
│ sidebar  │ main                      │ inspector      │
│ (240px)  │ (1fr, scroll-y)           │ (320px,        │
│ projects │ page-specific content     │  collapsible)  │
└──────────┴──────────────────────────┴─────────────────┘
```

* **Topbar** — brand-mark + page title + Cmd-K hint + theme toggle +
  auth indicator.
* **Sidebar** — `all hosts ▾` filter + `Filter projects…` search +
  `RECENTLY ASKED` + language groups (`GO`, `JAVASCRIPT`, `PHP`, …)
  with `★`-pinned project markers.
* **Main** — page content; layout choice (single column / card grid /
  split pane / tabs) belongs to the page.
* **Inspector** — context-aware widgets per page (KPI summary + live
  activity feed on the dashboard, project metadata + budget gauges on
  the project page, etc.). Collapse via `«` button (state persisted in
  `localStorage`); auto-collapses below 1280 px.

Linear-violet OKLCH palette, compact density, light/dark theme toggle.

### Per-page surfaces

- **Dashboard (`/`)** — **Quick Ask** card at the top (project picker +
  question → navigates to project page with pre-filled query), KPI strip
  (projects, active embeds, recent queries, bridge state, dispatcher
  health, host budget headroom), 2-column card grid (recent activity,
  Auto-reembed, FleetQ Bridge, Plugins, Recall Q&A history full-width,
  Project graph full-width). Inspector shows a KPI mini-strip plus a
  live SSE-driven activity feed with pulse-on-new.
- **Project page (`/projects/<name>`)** — five-tab system:
  **Overview** / **Memories** / **Trajectories** / **Q&A History** /
  **Settings**. Number keys `1`–`5` jump tabs; `#tab=<id>` URL hash
  makes shareable deep links. Inspector shows project metadata +
  24h budget consumption.
- **Memories tab** — split-pane editor: file list (left) + raw markdown
  textarea (centre) + bleach-sanitised live HTML preview (right).
  Toolbar: Save / Undo (`Cmd-Z`) / Redo (`Cmd-Shift-Z`) / `diff vs:`
  revision selector. Last-20 per-file history, side-by-side HTML diff,
  optional tag chip editor.
- **Network (`/network`)** — inter-project call graph rendered with a
  vendored Cytoscape build. Edge weights track real Harbormaster MCP
  calls (caller → target). Filters by host / project / tool / window;
  switchable graph / chat list view; SSE-driven live append. Aggregate
  stats at `/api/network/stats?window=…`.
- **Dispatcher trace (`/dispatcher`)** — live in-flight spans +
  last-100 completed spans rendered as a waterfall with parent / child
  nesting. Each span exposes tool, project, host, duration, and (where
  the backend emits it) tool-call sub-spans for the model's own tool
  use. Real backend token usage in the SSE `usage` event.
- **Cmd-K command palette** — bigram fuzzy-matched action launcher;
  shareable URLs via `?q=` pre-fill; pulls actions from a single catalog
  so every page surface adds itself for free.

Operator-facing reference: [`docs/operator-guide.md`](docs/operator-guide.md).

---

## Configuration

Zero-config by default. For any other layout, drop a TOML file at
`~/.config/harbormaster/config.toml`:

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

# Optional — opt in to Q&A history / recall
[history]
enabled = true

# Optional — daily call budgets
[budget]
daily_call_budget_per_tool = { ask_project = 200, delegate_task = 50 }
```

A per-project override at `./.harbormaster.toml` in your cwd takes
precedence over the user-level config. Validate at any time with:

```bash
harbormaster-mcp config check
```

Full schema (every section, key, type, default, valid range):
**[`docs/operator-config-reference.md`](docs/operator-config-reference.md)**.

---

## Backends

Harbormaster's backend abstraction is a Protocol; the project ships two
first-party implementations:

| Backend | Default for | Notes |
|---|---|---|
| `claude` (`claude -p`) | `[backends.default]` | The reference backend. Per-token streaming, real backend-reported token usage in the SSE `usage` event, tool_use sub-span instrumentation. |
| `codex` (Codex CLI) | opt-in via `[backends.codex]` | Token instrumentation parity (v12.0.0a1). Tool-use sub-span instrumentation parity (v17.0.0a2). Same ask / delegate / fan-out surface. |

Switching a project's backend is a TOML edit — no code changes. SSH hosts
each carry their own backend setting (`backend = "codex"` on the host
block) so you can mix backends across the fleet.

Pre-flight on each remote host: install the backend's CLI, authenticate
once, ensure project paths exist with their `CLAUDE.md` / `.serena/` in
place, and confirm passwordless SSH from your machine (`BatchMode=yes` is
enforced by Harbormaster).

---

## FleetQ Bridge integration (optional)

Install with the `[fleetq]` extra and Harbormaster registers itself as a
Bridge daemon, advertises its MCP tools as Platform Tools, publishes an
A2A Agent Card per project, and writes back semantic triples to the
federated KnowledgeGraph:

```bash
pipx install 'harbormaster-mcp[ui,fleetq]'
```

```toml
[fleetq]
enabled = true
register_as_bridge = true
base_url = "https://app.fleetq.net"
api_token_env = "FLEETQ_API_TOKEN"
heartbeat_interval = 30
```

```bash
export FLEETQ_API_TOKEN=...
harbormaster-mcp
```

Harbormaster shows up in the FleetQ Connections UI as
`harbormaster on <hostname>`. Reverse-tunnel calls flow from
FleetQ → Bridge → Harbormaster transparently with `text/event-stream`
forwarding (`X-Accel-Buffering: no` so reverse proxies don't buffer).

Discovered contract reference: [`docs/fleetq-bridge-contract.md`](docs/fleetq-bridge-contract.md).

---

## Versioning

Harbormaster ships on a proven alpha-cadence: each major (`vN.0.0`) is
preceded by a sequence of `vN.0.0aK` alpha tags, every alpha is a
PyPI-published release, and the GA tag `vN.0.0` is a no-code promotion
plus a cumulative retro doc.

The cadence has shipped GA 18 times (v1 through v18) without a single
forced rollback. Current head: **v19.0.0a1**.

Every behaviour change lands in one alpha and shows up in
[`CHANGELOG.md`](CHANGELOG.md) under the corresponding major release.
Per-major retros under [`docs/sprint-retro-harbormaster-v*.md`](docs/)
are the source-of-truth narrative if you want the why behind a change.

PyPI publishing is automated via Trusted Publishing (OIDC) — no API
tokens in the repo. Tag-pushes to `v*` trigger the publish workflow.

---

## Pre-commit hooks

Two repo-local hooks ship in [`.pre-commit-config.yaml`](.pre-commit-config.yaml):

- **`harbormaster-config-check`** — validates [`examples/harbormaster.toml`](examples/harbormaster.toml) against the TOML schema. Fails the commit on any schema error.
- **`harbormaster-config-doc-parity`** — fails the commit if a Pydantic field is added to `src/harbormaster/config.py` without a matching mention in [`docs/operator-config-reference.md`](docs/operator-config-reference.md). On failure, the hook emits a copy-paste-ready markdown stanza so adding the missing doc takes seconds.

Install once:

```sh
uv sync --extra dev
bash scripts/post_sync_install_hooks.sh
```

Or with a system / pipx pre-commit: `pipx install pre-commit && pre-commit install`.

---

## Contributing

Harbormaster is primarily a single-operator tool. Pull requests are welcome
when they fit the alpha-per-feature cadence:

1. One feature per branch — `feat/v<N>.<P>-<phase-name>`.
2. Tests + `mypy --strict` + `ruff` clean before requesting review.
3. Update [`docs/operator-config-reference.md`](docs/operator-config-reference.md) for any new config field (the doc-parity hook will tell you).
4. Keep changes additive when possible — Harbormaster's invariant is
   zero breaking changes per release line.

Operator workflows and deployment scenarios are documented in
[`docs/operator-guide.md`](docs/operator-guide.md).

---

## Lineage

Harbormaster v1.0 grew out of `project-router-mcp` v0.1 (2026-05-08). v0.1
git history is preserved on this repository — the v0.1 single-file server
lived at `src/server.py` in commits prior to the v1.0 scaffolding refactor.

---

## License

MIT — see [LICENSE](LICENSE).

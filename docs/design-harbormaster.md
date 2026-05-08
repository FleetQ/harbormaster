# Harbormaster — Design Doc

**Status**: Draft (Think phase)
**Sprint**: 2026-05-08
**Working name**: Harbormaster (full: *FleetQ Harbormaster*)
**Origin**: evolution of `~/htdocs/project-router-mcp` (v0.1, 2026-05-08)
**License (proposed)**: MIT
**Package (proposed)**: `harbormaster-mcp` on PyPI

---

## 1. Problem statement

A power-user developer maintains 50+ active projects, each with its own conventions, `CLAUDE.md`, Serena memories, and tooling. To ask any project a question or delegate a task today, the user must:

- Switch terminal + IDE working directory
- Wait for tooling (Serena, Claude, agent stack) to re-initialize
- Lose conversational context in the main session

Cost: 4–8 `cwd` switches per developer per day. At agency / FleetQ scale, this becomes the dominant friction in multi-project work.

`project-router-mcp` v0.1 solves this locally: one MCP server exposes `list_projects`, `project_status`, `ask_project`, `delegate_task`. Calls route to per-project Claude subagents that auto-load that project's CLAUDE.md + Serena memories. Performance measured 2026-05-08: status 170ms, ask 30s, list 857ms across 52 projects.

**Harbormaster is the v1**: production-grade, OSS-ready, multi-host (SSH fleet), FleetQ-native, observable, with a Live UI.

---

## 2. Audience (layered tiers)

| Tier | Persona | Pain today | Harbormaster value |
|------|---------|------------|---------------------|
| **1 — Solo CC user** | Indie dev, 10+ side repos under `~/code/` | Cwd switches lose context; per-project CLAUDE.md duplicated effort | Federation across local projects; single install |
| **2 — Agency / consultant** | Multi-client dev, multiple VPS / staging envs | Same as Tier 1 + remote-host context loss | SSH fleet routing; per-project encrypted credentials |
| **3 — FleetQ team customer** | Already paying for FleetQ orchestration | Local agents and FleetQ live in separate worlds | Drop-in Bridge / Platform Tool registration, UI parity |

Distribution model: progressive complexity. Tier 1 with `pip install harbormaster-mcp`. Tier 2 with one TOML hosts file. Tier 3 with a single FleetQ Marketplace activation.

---

## 3. Scope — phased v1

User explicitly requested **full** v1 (local + SSH + FleetQ + Live UI). To preserve shippable milestones inside that, we phase v1 into three releases:

### v1.0 — OSS launch (target: 1–2 weeks)

- **Config-driven project discovery**: TOML config replaces hard-coded `~/htdocs/*`. Schema: `[projects] glob = ["~/htdocs/*", "~/work/*"]; exclude = [...]`.
- **Pluggable backend abstraction**: `BackendInterface` with implementations for `claude` (default), `codex`, `aider`, `gemini-cli`. Start with `claude`, abstract early so contributors can add others.
- **SSH multi-host hardening**: extend the in-progress `host` parameter (background agent ~80% done). Add `[hosts]` section in config. `list_hosts()` reads `~/.ssh/config` + config overrides.
- **Dual transport**: stdio (default, for Claude Code / Desktop) + HTTP/SSE (for Live UI + remote MCP clients). FastMCP supports both.
- **Live UI**: FastAPI embedded in same process. HTMX + Alpine.js + Tailwind. SSE for live stream. Single port (default 7531). See §5.
- **New tool**: `fan_out_ask(question, project_filter, host_filter, max_concurrency=5)` — parallel multi-project Q&A with map-reduce synthesis.
- **Packaging**: PyPI (`harbormaster-mcp`), `uvx harbormaster-mcp`, MIT license, optional Homebrew tap.
- **Docs**: README, quickstart, configuration reference, contributing guide.
- **Tests**: pytest suite ≥80% coverage on the routing layer.

### v1.1 — FleetQ-native (target: +1 week)

- **FleetQ Platform Tool seed entry**: PR into `agent-fleet/base/database/seeders/PopularToolsSeeder.php` registering Harbormaster as an `McpStdio` tool with `risk_level = Read` (write delegation stays read-only). Teams activate via `/tools` UI with their own credentials.
- **FleetQ Bridge integration**: Harbormaster registers itself as a Bridge endpoint via `POST /api/v1/bridge/register`. Heartbeats every 30s. Discovery surfaces in FleetQ UI.
- **A2A Agent Card per project (optional)**: each `~/htdocs/*` project publishes itself as an A2A v0.3 agent card. FleetQ already supports authenticated A2A endpoints.
- **Optional FleetQ adapter**: `pip install harbormaster-mcp[fleetq]`. When configured, writes Q&A trajectories to FleetQ Memory domain. Fully optional — no behavior change without it.

### v1.2 — Compounding (target: +2 weeks)

- **Q&A history with semantic dedup**: local sqlite-vec (or pgvector if FleetQ adapter is on). Repeat questions hit cache. Searchable history in UI.
- **Federated KG via FleetQ**: writes to `KnowledgeGraph` domain. Cross-project semantic search using PPR + Louvain communities (already implemented in FleetQ).
- **Auto project graph**: parse package manifests (`composer.json`, `package.json`, `pyproject.toml`) to discover cross-project dependencies. Visualize in UI.
- **Cross-session memory recall**: when user asks a question, Harbormaster checks past trajectories for similar Q&As across the fleet and surfaces them.

---

## 4. Headline feature — Live Streaming UI

The MCP server is invisible plumbing. The UI is the **viral surface** — what people screenshot, blog about, share.

**What it shows**:

1. **Project grid** — 50 cards, each with: project name, last commit, framework badge (Laravel/Next/Python/...), Serena memories count, last-asked timestamp, "Ask…" button.
2. **Live query feed (SSE)** — real-time stream of in-flight queries: `pinporn ← "did the cron run?" — 4.2s elapsed — streaming answer…`. Like `htop` for AI queries.
3. **History / audit** — past Q&A log, searchable, with token / cost / duration per call. Click to replay.
4. **Fleet view** — local + remote hosts as a list/map. Online/offline status, claude version per host, queue depth.
5. **Cost panel** — tokens + $ per project, per host, time-series.
6. **Memory inspector** — read-only view of each project's `CLAUDE.md` + Serena memories. No need to open files.
7. **Replay** — re-ask any past question; diff old vs new answer.

**Tech**: FastAPI in same process as MCP server. HTMX for interactivity, Alpine.js for state, Tailwind for styling. Static HTML served from Python. SSE for live updates. Targets ~500 LOC of frontend, no npm step. Tauri wrapper is post-v1.2 candidate.

---

## 5. Whoa-list (all four desired)

| Whoa | v1 phase | Description |
|------|----------|-------------|
| Parallel fan-out | v1.0 | `fan_out_ask(...)` to 50 projects in parallel, map-reduce synthesis |
| Live streaming UI | v1.0 | See §4 |
| Cross-session memory | v1.2 | Past Q&A semantic recall |
| Auto project graph | v1.2 | Discover and visualize cross-project deps |

---

## 6. Compounding mechanism

User-selected: **federated KG via FleetQ**. Every trajectory written to FleetQ Memory + KnowledgeGraph domains. With each interaction:

- Q&A history grows → repeat questions get cache hits
- KG accumulates entity-relation facts across projects → cross-project semantic search becomes more relevant
- FleetQ's `ExtractSkillFromTrajectoryJob` surfaces reusable skill candidates from clusters of similar Q&As → user can promote them to durable skills

**Privacy**: opt-in. Standalone OSS user never writes to FleetQ unless they opt in via config.

---

## 7. Differentiators

| vs. | Difference |
|-----|------------|
| Smithery / MCP marketplaces | Not a registry — federation / routing layer over existing projects |
| Goose / Aider | Not an agent — orchestrates between per-project agents |
| Letta / Mem0 | Local-first; no monolithic memory store; per-project memory respected |
| Bare Claude Code | No cwd switching; per-project memory loads automatically |
| Existing MCP servers | One MCP exposing N project-scoped sub-MCPs is novel; SSH fleet routing is novel |

Positioning line:

> *"Harbormaster is the GitHub Actions Runner for FleetQ — OSS, self-host works fully, but 99% of the value lights up when paired with the platform."*

---

## 8. Out of scope (v1)

- **Cross-host write delegation** (`allow_writes=True` over SSH). Stays "fails closed" on remote in v1.
- **Multi-tenancy in standalone OSS mode**. FleetQ provides this when used.
- **Mobile / native UI**. Web-only for v1. Tauri wrapper deferred.
- **Non-Claude backends in v1.0**. Codex/Aider/Gemini deferred to v1.0.x patches.
- **Plugin / extensions API**. Deferred to v2.
- **Authentication for the local UI**. v1 assumes localhost only. Multi-user UI auth in v1.1+.

---

## 9. Success criteria

| Phase | Metric | Target |
|-------|--------|--------|
| v1.0 launch | Show HN points OR GitHub stars in 30 days | ≥100 points OR ≥500 stars |
| v1.1 | FleetQ teams activating Harbormaster Platform Tool | ≥5 |
| v1.2 | User testimonials on context-switch reduction | ≥10 |
| v1.x cumulative | Daily active routes per user | ≥3 |

---

## 10. Open questions (need user decision before Plan phase)

1. **Repo strategy**: rename `~/htdocs/project-router-mcp/` → `~/htdocs/harbormaster/` (preserve git history) **or** fresh repo and archive v0.1?
2. **Time budget**: aggressive (3-week total for v1.0–1.2) **or** comfortable (6-week total)?
3. **GitHub org**: `escapeboy/harbormaster` (personal) **or** new `fleetq-ai/harbormaster` org?
4. **License**: MIT (most permissive, most adoption) **or** Apache 2.0 (patent grant)?

These are pre-Plan decisions. Defaults if user doesn't object: rename existing repo, 4-week total budget, `fleetq-ai/harbormaster` org, MIT.

---

## 11. Risks & mitigations

| Risk | Likelihood | Mitigation |
|------|------------|-----------|
| Scope creep — full v1 spans 3 phases | High | Strict v1.0 → v1.1 → v1.2 cut-lines; each is independently shippable |
| `claude -p` API changes break SSH fan-out | Medium | Pin tested versions; backend abstraction layer absorbs change |
| FleetQ Bridge contract churn | Medium | Adapter is optional; ship v1.0 OSS-only first, then v1.1 FleetQ-native after Bridge contract stabilizes |
| Live UI XSS via project answers | High if naive | Render answers as Markdown via server-side sanitizer (bleach), CSP headers, no inline scripts |
| Shell injection in SSH paths | High if naive | Already mitigated via `shlex.quote` (background agent v1); add fuzz tests |
| Anthropic seat cost on remote VPS | Medium | Document clearly; future: support local llama-server backend |

---

## 12. Hand-off to Plan phase

The Plan phase produces:

- `docs/architecture-harbormaster.md` — component diagram, data flow, transport choices, storage schema, UI structure, FleetQ integration contract.
- `docs/test-plan-harbormaster.md` — unit / integration / e2e cases, fuzz fixtures, smoke matrix.

Plan must answer:

- Exact module layout (`harbormaster/{config,backends,transport,ui,fleetq,...}`).
- Config schema (TOML).
- MCP tool list with full schemas.
- UI route map + SSE event format.
- FleetQ Bridge handshake sequence.
- Storage decision (sqlite-vec vs pgvector vs both).

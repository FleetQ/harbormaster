# Sprint Retro — Harbormaster v1.0.0 (GA)

**Date:** 2026-05-09
**Theme:** **`v1.0.0` GA shipped.** Drop of the alpha suffix after
20 alpha tags (v0.1.1 + a1 → a20). All four v1.2 phases shipped this
session. This retro spans the full a1→GA arc — what shipped, what was
deferred, and what worked across the journey.

## What landed (the full a1→GA arc)

### `harbormaster` (this repo)

| Tag | Date | Capability |
|-----|------|------------|
| `v0.1.1` | 2026-05-08 | Original `project-router-mcp` v0.1 single-file MCP, renamed in-place to harbormaster |
| `v1.0.0a1` | week 1 | Repo scaffolding: pyproject.toml, MIT license, src/harbormaster/ layout, FastMCP server, stdio transport |
| `v1.0.0a2` | week 1 | Backend abstraction (Protocol-based), `claude` backend default |
| `v1.0.0a3` | week 1 | Six MCP tools: list_projects, list_hosts, project_status, ask_project, delegate_task, fan_out_ask |
| `v1.0.0a4` | week 1 | Live UI (FastAPI + HTMX + Alpine + Tailwind, single port, dashboard at `/`) |
| `v1.0.0a5` | week 2 | SSH host fan-out for remote project routing |
| `v1.0.0a6` | week 2 | FleetQ Bridge register/heartbeat/disconnect (`[fleetq]` extra) |
| `v1.0.0a7` | week 2 | A2A Agent Cards published to FleetQ |
| `v1.0.0a8` | week 2 | PyPI Trusted Publishing setup; first PyPI release |
| `v1.0.0a9` | week 3 | Bridge HTTP-tunnel mode (Path C) — relay-binary path (Path B) explicitly skipped |
| `v1.0.0a10` | week 3 | SSE streaming for `/mcp/{server}` (heartbeat + final result) |
| `v1.0.0a11` | week 3 | `claude --output-format stream-json` iterator backend |
| `v1.0.0a12` | week 3 | `ask_local_stream` wired into SSE dispatch with chunk events |
| `v1.0.0a13` | week 3 | SSH chunk streaming + deterministic 400 on bad project |
| `v1.0.0a14` | week 4 | Streaming widened to `delegate_task` + extracted generic helpers |
| `v1.0.0a15` | week 4 | A2A Agent Card per project + `update_endpoints` watch + nginx proxy_buffering recipe |
| `v1.0.0a16` | week 4 | FleetQ Memory writeback + 8-section operator guide (closes v1.1) |
| `v1.0.0a17` | week 5 | Q&A history with sqlite-vec + fastembed + `recall_qa` tool (v1.2 phase 1) |
| `v1.0.0a18` | week 5 | Auto project graph from manifest parsing + `project_graph` tool (v1.2 phase 3) |
| `v1.0.0a19` | week 5 | Federated KG via FleetQ KnowledgeGraph + heuristic triple extraction (v1.2 phase 2) |
| `v1.0.0a20` | week 5 | Cross-session memory recall via auto-grounded prompts (v1.2 phase 4) |
| **`v1.0.0`** | **2026-05-09** | **GA — alpha suffix dropped, no new code** |

## Capabilities at GA

### 8 MCP tools

`list_projects · list_hosts · project_status · ask_project · delegate_task · fan_out_ask · recall_qa · project_graph`

All accept optional `host` for SSH fan-out. `recall_qa` and
`project_graph` are v1.2 additions; the other six are v1.0 / v1.1.

### Two console scripts

- `harbormaster-mcp` — stdio (default) + `--transport sse|streamable-http`. Auth via `HARBORMASTER_MCP_TOKEN`.
- `harbormaster-ui` — FastAPI dashboard + `POST /mcp/{server}` HTTP-direct + `GET /agent-card/{project}` A2A v0.3 + `GET /api/graph`. Auth via `HARBORMASTER_UI_TOKEN`.

### Three optional pyproject extras

- `[ui]` — FastAPI dashboard
- `[fleetq]` — Bridge / Memory / KG integration
- `[history]` — Q&A history with sqlite-vec + fastembed

### Three best-effort writeback hooks

All gated, all silent on failure, all in `tools/_helpers.run_backend`:
1. `_maybe_writeback_to_fleetq` (a16) — trajectories to FleetQ Memory
2. `_maybe_record_qa` (a17) — local sqlite Q&A history
3. `_maybe_extract_and_writeback_kg` (a19) — heuristic triples to FleetQ

Plus one synchronous prompt augmentation: `build_grounded_prompt` (a20)
prepends recall context BEFORE `run_backend`.

### CI pipeline

- 8 jobs per PR: test matrix (Ubuntu+macOS × py3.11/3.12/3.13) + smoke-http + smoke-ui + smoke-ui-auth + smoke-ui-with-token + smoke-mcp-streaming + gated smoke-fleetq + build
- PyPI Trusted Publishing on tag push
- 392 tests + 1 intentional skip
- mypy --strict + ruff clean

## Real numbers (a1 → GA)

- **20 alpha tags** shipped + 1 GA tag
- **14 PRs** opened and merged on harbormaster (#1–#14)
- **~6 weeks elapsed** from project-router-mcp v0.1 (2026-04-13) to v1.0.0 GA (2026-05-09)
- **~31 days** from harbormaster v0.1.1 rename (2026-05-08) to v1.0.0
- **0 → 392 tests** + 1 intentional skip
- **0 → 40 source files**
- **0 → ~7000 LOC** in src/harbormaster/ (excluding tests + docs)
- **20 sprint retros** (one per alpha tag) preserving the full evolution
- **0 backward-incompatible changes** across all 20 alpha tags

## What worked

- **One PR per action item, one ship commit per alpha tag.** Every
  feature lived on its own branch, got its own PR with tests, then
  landed via squash-merge to main. The post-merge ship commit
  (bump + retro) was always a separate commit on main, never
  squashed in. Result: every PyPI release maps to one feature, not
  a dump of unrelated changes.
- **Three-gate opt-in pattern (a16) reused across a17, a19, a20.**
  `[domain] enabled` + `[domain] sub_feature` + credential / package
  check. Each new domain (FleetQ writeback → history → KG → grounding)
  followed the same shape, so reading one tells you how the next
  works. Operators tune privacy-vs-feature tradeoffs without
  recompiling.
- **`_maybe_*` naming convention for fire-and-forget hooks.** Self-
  documenting: "this might do something, might not, you don't need
  to know which." Pairs with silent-on-failure semantics — the
  function NAME tells you not to expect a return value.
- **One sprint retro per alpha tag, from a shared template.** The
  retros read as the project's historical record. Future-me reading
  retro a14 sees exactly what shipped and what to expect when reading
  a15. The template's "Action items for next sprint" section lets
  retro a14 directly seed retro a15's "What landed" — accountability
  loop without overhead.
- **Discriminator-on-existing-endpoint over new endpoints.** When
  FleetQ-side coordination would have blocked progress (KG triples
  in a19), we extended `/api/v1/memory` with a `type: "kg_triple"`
  field instead of waiting for `/api/v1/knowledge-graph`. Triples
  land as opaque records until FleetQ ships KG-aware processing —
  still durable, still useful.
- **Local-first storage, FleetQ as additive layer.** sqlite-vec for
  the Q&A history; FleetQ Memory writeback is the second persistence
  hop, fully optional. Standalone OSS works without any FleetQ
  integration. This kept the "FleetQ is broken / unreachable" failure
  mode from breaking the core Q&A loop.

## What to change / next (deferred to v1.1+ post-GA)

- **Streaming-path auto-grounding.** Auto-grounding ships only on
  the JSON path; SSE streaming bypasses `tools.ask` and calls the
  backend directly. Wiring is mechanical but needs the streaming
  prompt builder to live in a more visible spot.
- **`fan_out_ask` auto-grounding.** Per-target grounding would be
  useful but multiplies latency. Needs real-world cost data first.
- **Grounding metric / hit-rate dashboard.** We bump `recall_count`
  but don't surface it. A future `harbormaster-mcp stats` subcommand
  could surface grounding hit rate alongside recall_count + most-
  recalled rows + oldest entry per host.
- **Lockfile-driven version pinning in `project_graph`.** Parser
  collects deps, not resolved versions. Adding lockfile parsing
  (uv.lock, package-lock.json, composer.lock, Cargo.lock, go.sum)
  is v2 territory.
- **Live KG smoke in CI.** `smoke-fleetq` exercises the trajectory
  writeback path; doesn't yet POST a triple and assert round-trip.
- **LLM-based triple extraction.** Heuristics ship now; an LLM
  sweep over historical trajectories would catch what regex misses.
  Cost-per-call constraint pushed this to v2.

## Out-of-scope (still — for v2)

- Backends other than Claude.
- Plugin / extensions API.
- Tauri / Electron native UI wrapper.
- Relay-binary path (Path B) — explicitly skipped in favour of Path C.
- Per-token streaming through relay-mode bridge.
- Cross-host recall aggregation.
- Cross-host triple aggregation (FleetQ-side concern).
- Embedding upgrade-in-place.
- Transitive deps in `project_graph`.

## Acknowledgements

This release builds on:

- **MCP / FastMCP** — Anthropic's Model Context Protocol + Python SDK
- **Pydantic** — config + wire-shape validation
- **FastAPI + sse-starlette + uvicorn** — Live UI + HTTP/SSE transport
- **httpx** — FleetQ writeback HTTP client
- **sqlite-vec + fastembed** — Q&A history (v1.2 phase 1)
- **HTMX + Alpine.js + Tailwind via CDN** — Live UI without a build step
- **Claude Code** — the subagent every project ships its memories to
- **uv + hatchling** — packaging + Trusted Publishing
- **GitHub Actions** — CI matrix + auto-publish

Thanks also to the **FleetQ ecosystem** — the integration layer that
made v1.1 (Bridge, Memory) and v1.2 phase 2 (KG) shippable as
add-ons rather than rewrites.

---

After this release: harbormaster is **stable**. Future PRs target
v1.1.x patches and v2 features.

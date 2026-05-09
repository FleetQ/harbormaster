# Sprint Retro — Harbormaster v2.0.0 (GA)

**Date:** 2026-05-09
**Theme:** **`v2.0.0` GA shipped.** Drop of the alpha suffix after seven
v2 alpha tags (a1 → a7), all delivered the same evening as v1.0.0 GA.
This retro spans the full v2 arc — what shipped, what was deferred,
and what worked across the journey.

## What landed (the full a1→GA arc)

### `harbormaster` (this repo)

| Tag | Capability |
|-----|------------|
| `v2.0.0a1` | Lockfile-aware transitive deps in `project_graph` (uv.lock, poetry.lock, requirements.txt, package-lock.json, composer.lock, Cargo.lock, go.sum) |
| `v2.0.0a2` | Embedding upgrade-in-place: `embedding_meta` schema row, drift detection at QAStore.open(), `harbormaster-mcp reembed` CLI with resumable rowid marker |
| `v2.0.0a3` | Multi-backend support: CodexBackend mirroring ClaudeBackend; `default_backend` + `backends_for_project` config for per-project routing; `Backend.cfg` promoted to Protocol |
| `v2.0.0a4` | Entry-point plugin API: `harbormaster.tools` group, `[plugins].enabled` + `allow=[...]` allowlist (deny-by-default), failure isolation across import + register |
| `v2.0.0a5` | LLM-based triple extraction: `[fleetq] kg_extractor = "heuristic"\|"llm"\|"both"`, fence/prose-tolerant JSON parser, dedup by (s,p,o) |
| `v2.0.0a6` | Cross-host recall aggregation: `recall_qa(host="all")` fan-out across local + every configured host, score-merged + capped, per-host failure isolation |
| `v2.0.0a7` | Per-token streaming through Bridge: `BridgeRelay.publish_chunk()` / `publish_error()` + `chunk_handler` that streams yielded text deltas as `client-relay.chunk` events |
| **`v2.0.0`** | **GA — alpha suffix dropped, no new code** |

## Capabilities at GA

### 8 MCP tools (unchanged from v1)

`list_projects · list_hosts · project_status · ask_project ·
delegate_task · fan_out_ask · recall_qa · project_graph`

v2 widened existing tools rather than adding new ones:
- `project_graph` gains `transitive: bool = False`
- `recall_qa` gains `host="all"` mode
- All ask_*/delegate_* paths route through `get_backend_for_project()`

### 2 backends (vs. 1 in v1)

`claude` (default) and `codex`. Per-project override via
`[backends_for_project] my-frontend = "codex"`. Streaming gates
preserved — Codex without streaming gracefully falls back to buffered.

### Plugin API

Third-party MCP tools ship in their own distributions. Operators opt
in via `[plugins].enabled = true` + explicit `allow = [...]`
allowlist. Plugin contract IS the built-in tool contract:
`def register(mcp, config) -> None`. Example plugin in
`examples/plugins/harbormaster-plugin-hello/`.

### KG extraction modes

`[fleetq] kg_extractor`:
- `"heuristic"` (default) — regex-only, free, v1.2 phase 2 behaviour
- `"llm"` — one extra `ask_local()` per answer, structured JSON triples
- `"both"` — run both, dedup by `(subject, predicate, object)`, keep highest confidence

### Cross-host recall

`recall_qa(host="all")` aggregates across the local store + every
configured host's per-host SQLite (all on the local machine — no SSH
needed for recall). Per-host failures isolated; broken stores don't
block the rest.

### Bridge per-token streaming

BridgeRelay publishes `client-relay.chunk` events back through the
Pusher channel as multi-chunk responses. `chunk_handler` parameter
turns the relay into a request → handler → stream-back path. Wire
shape matches `docs/fleetq-relay-protocol.md` exactly.

### Embedding upgrade-in-place

Flipping `[history] fastembed_model` no longer silently misaligns
recall. Drift is detected at every `QAStore.open()` and resolved by an
explicit `harbormaster-mcp reembed` run. Resumable on rowid; safe to
interrupt; recreates `qa_vec` on dim change.

## Real numbers (cumulative across the v2 arc)

- 7 alpha PRs opened / merged (#15 #16 #17 #18 #19 #20 #21)
- 115 new unit tests added across the seven phases (392 → 507 pass, 1 skip)
- mypy --strict: 40 → 45 source files, clean across all phases
- ruff: clean across all phases
- Backwards-incompatible changes: 0 (every new behaviour is opt-in via config)
- 8 published versions: v2.0.0a1 → v2.0.0a7 → v2.0.0
- New modules: `graph/lockfile.py`, `history/cli.py`, `backends/codex.py`,
  `plugins.py`, `fleetq/triples_llm.py`
- Lines added: ~3,700 across feature + retro PRs
- Time from v1.0.0 GA to v2.0.0 GA: same evening

## What worked

- **Per-phase retro AS PART of the ship commit.** Same as v1: every
  alpha tag carries its own retro on the same day it ships. The
  numbers, the "what worked," the "what to change" are written while
  the work is fresh. This GA retro is then a synthesis pass — easy
  because the per-phase retros caught the details.

- **One PR per phase + squash-merge.** Same flow as v1.0.0:
  branch → PR → CI → squash-merge → version bump → retro → tag → push.
  No interactive rebases, no bisect-hostile fixup commits — every
  alpha tag points at exactly one squashed commit.

- **Opt-in everything.** Every new behaviour in v2 is gated:
  `transitive=False` (a1), drift detection logged-only (a2),
  `default_backend = "claude"` (a3), `[plugins].enabled = false` (a4),
  `kg_extractor = "heuristic"` (a5), `host="all"` opt-in (a6),
  `chunk_handler=None` (a7). Result: a v1 deployment that pulls v2.0.0
  off PyPI sees zero behaviour change.

- **Protocol-first multi-backend design.** Widening `get_backend()`'s
  return type from `ClaudeBackend | None` to `Backend | None` caught
  two implicit assumptions in `_helpers.py` (Backend has `cfg`;
  streaming isn't on the Protocol) before they shipped. Promoting
  `cfg` to the Protocol + keeping `hasattr` gates for streaming kept
  the migration cost to one PR.

- **Lockfile parsers as a sibling module.** v2.0.0a1 didn't refactor
  `parser.py` — it landed `lockfile.py` as a sibling and lazy-imported
  it from `parse_project()`. Manifest-only callers don't pay the
  lockfile import cost; lockfile-aware callers don't have to know
  about the manifest internals.

- **Local-only LLM extraction.** v2.0.0a5 deliberately scoped LLM
  extraction to local backends. Remote SSH per-call would have
  doubled remote-execution latency. The fall-through to heuristic for
  remote `host` arguments is one `is_remote(host)` check — no extra
  config knob needed.

- **Wire-shape doc as the source of truth.** v2.0.0a7 implemented
  `client-relay.chunk` + `client-relay.error` exactly as documented
  in `docs/fleetq-relay-protocol.md` (filed during v1.0.0a8). When
  FleetQ-side decoder ships, no protocol mismatch — they're reading
  from the same doc.

- **Bracket-aware JSON scanner.** v2.0.0a5's parser handles
  bracket characters inside JSON strings via a simple depth + string-
  state counter. Took ~12 lines vs. the regex prototype that
  silently failed on `"GET /api/[id]"`.

## What to change / next (v3 / future)

- **agent.request → MCP dispatcher wiring.** v2.0.0a7 ships the
  publish surface. Wiring `agent.request → tool selection → permission
  check → ask_local_stream → chunk_handler iterator` is real work
  that didn't fit a single phase. Defer to v3 or pull in for v2.1.

- **Pysher worker-thread offloading.** `_dispatch_chunk_handler` runs
  on Pusher's internal thread. Heavy handlers block event delivery
  for that channel. A queue + worker thread pool would isolate them.

- **Parallel cross-host recall.** v2.0.0a6 iterates hosts
  sequentially. With 5+ hosts, latency adds up. `ThreadPoolExecutor`
  per-host call is a clean win when somebody actually has 5+ hosts.

- **No `harbormaster-mcp plugins list`.** Useful introspection CLI
  the v2.0.0a4 retro flagged. Trivial follow-on.

- **No CI smoke for `transitive=True`, `kg_extractor=llm`, `host="all"`,
  `chunk_handler`.** Each new mode has unit tests but no end-to-end
  smoke. Adding these would catch wiring regressions across Python
  versions.

- **pnpm-lock.yaml + yarn.lock.** Deferred from v2.0.0a1 because they
  need a YAML / proprietary parser. Drop in when somebody runs into a
  pnpm-heavy project.

## Out-of-scope (still — pushed past v3 too)

- Tauri / Electron desktop UI wrapper — too big, no demand.
- Relay-binary path (Path B) — Path C HTTP tunnel covers the use case.
- Backend sandbox / capability restrictions — Python's import system
  is fully privileged; the plugin allowlist is the trust boundary.
- LLM-based extraction for remote hosts — per-call SSH cost not
  justified.
- Auto-reembed on drift detection — the operator chooses when to
  spend the embedding compute, deliberately.
- Cross-model vector translation — when models disagree, you re-embed.

## Release flow used (for the next major)

```
1. Branch:   feat/v2-<phase-name>
2. Implement, test (mypy strict + ruff + pytest); local pre-flight
3. Commit + push; open PR
4. Watch CI → squash-merge to main
5. Bump __version__ on main
6. Write docs/sprint-retro-harbormaster-v2.0.0a<N>.md from TEMPLATE
7. Commit "ship: bump to 2.0.0a<N> + sprint retro"
8. Tag v2.0.0a<N> and push tag (PyPI Trusted Publishing fires)
9. Verify on https://pypi.org/project/harbormaster-mcp/
10. Repeat for next phase
11. After last alpha → GA: bump to 2.0.0, write this retro, tag v2.0.0
```

This is the same shape v1 used. It compounds: by alpha 4 the muscle
memory makes each phase shippable in one focused work block.

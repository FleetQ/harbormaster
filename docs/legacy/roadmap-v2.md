# Harbormaster v2 Roadmap

**Drafted:** 2026-05-09 (after v1.0.0 GA shipped same day)

v1 shipped a single-backend, claude-only routing platform. v2 widens
the platform to multi-backend, plugin-extensible, lockfile-aware, with
upgrade paths for the embedding store and richer KG extraction.

Every phase is a separate alpha tag (`v2.0.0a1` … `v2.0.0aN`) with its
own PR + sprint retro, mirroring the v1 release flow.

## Out-of-scope for v2 (defer to v3+)

- Tauri / Electron desktop UI wrapper (huge surface; no demand yet)
- Relay-binary path (Path B) (Path C HTTP tunnel covers the use case)
- Embedding model fine-tuning / training (use upstream)
- Built-in IDE extension (VS Code / JetBrains) — the MCP server already
  works with any MCP-compatible client

## Phases

### Phase 1 — Lockfile-aware deps + transitive graph (`v2.0.0a1`)

Extend `harbormaster.graph.parser` to read lockfiles in addition to manifests:
- `uv.lock` / `poetry.lock` / `requirements.txt` (Python)
- `package-lock.json` / `pnpm-lock.yaml` / `yarn.lock` (Node)
- `composer.lock` (PHP)
- `Cargo.lock` (Rust)
- `go.sum` (Go)

Add transitive-closure mode to `graph.builder`. Extend `project_graph`
MCP tool with `transitive: bool = False` argument and `depth: int = 0`
cap. Cache invalidates on lockfile mtime change.

Internal-only; no FleetQ wire change, no plugin API. Pure-Python parsers
for each lockfile format. Heuristic fall-through when lockfile is absent.

### Phase 2 — Embedding upgrade-in-place (`v2.0.0a2`)

Right now flipping `[history] fastembed_model` silently misaligns recall
(old vectors at old dim vs. new query at new dim). Phase 2 detects the
mismatch and re-embeds.

- New `embedding_meta` schema row: `(model, dim, created_at)`
- On `QAStore.open()`: compare config model vs. stored model; if drift,
  log + offer to re-embed
- New CLI: `harbormaster-mcp reembed --batch-size 100 --resume`
- Resume marker on rowid; safe to interrupt
- New tests: drift detection, resumable batch, dim mismatch handling

### Phase 3 — Multi-backend: Codex (`v2.0.0a3`)

Add `harbormaster.backends.codex` mirroring `claude.py`. Codex CLI is
similar enough that the Protocol contract holds. Per-project backend
override via existing `backends_for_project: dict[str, str]` config map
(or default).

- New `[backends.codex]` config block
- New tests: parity with claude over the four backend methods
- Gated on `codex` binary being on $PATH; soft-fail when missing

### Phase 4 — Plugin API (`v2.0.0a4`)

Entry-point-based plugin discovery for third-party MCP tools.

- `importlib.metadata.entry_points(group="harbormaster.tools")`
- Plugin contract: `def register(mcp: FastMCP, config: HarbormasterConfig) -> None`
- `[plugins] enabled = true` + explicit `allow = ["plugin-pkg-1", ...]`
  allowlist (default deny)
- Loaded plugins logged at startup; failures swallowed with warning
- Example plugin in `examples/plugins/harbormaster-plugin-hello/`
- Tests: discovery, allowlist enforcement, registration failure isolation

### Phase 5 — LLM triple extraction (`v2.0.0a5`)

Replace the heuristic in `harbormaster.fleetq.triples` with a prompt-based
extractor when configured.

- New `[fleetq] kg_extractor = "heuristic" | "llm" | "both"` (default heuristic)
- LLM extractor calls the configured backend in a one-shot prompt that
  asks for `subject -> predicate -> object` triples
- Falls back to heuristic on parse failure
- Token budget cap to prevent runaway calls

### Phase 6 — Cross-host recall aggregation (`v2.0.0a6`)

`recall_qa(host=None)` currently scopes to one host's per-host SQLite.
Phase 6 adds `host="all"` to fan out across configured `[hosts.*]` and
merge by score.

- Per-host SSH fetch of `harbormaster.db.<host>` segment (read-only,
  reuses ssh streaming infra)
- Score-merge top-K across all hosts; cap at config-driven max
- Tests with two stub hosts; integration smoke gated on hosts being
  configured locally

### Phase 7 — Per-token streaming through Bridge (`v2.0.0a7`)

Bridge HTTP-tunnel mode currently delivers full result payload.
Phase 7 chunks through Pusher events so remote callers see live tokens.

- Wire `chunk` SSE events → Pusher event `chunk`
- Final `result` → Pusher event `result`
- New Bridge contract section in `docs/fleetq-bridge-contract.md`
- Coordinated with FleetQ-side decoder (defer hard-fail if FleetQ not ready;
  feature-flag the chunk events)

### v2.0.0 GA

Drop alpha. Write `docs/sprint-retro-harbormaster-v2.0.0.md`. Bump README
status. No new code in the GA tag — just the version bump (mirroring v1.0.0).

## Already-decided (don't re-litigate)

- Same release flow as v1: branch per phase, PR with full CI, squash-merge,
  bump version, retro, tag, push, PyPI auto-publishes via Trusted Publishing
- All new behavior is opt-in via config gates (matching v1 discipline)
- No breaking changes to the v1 tool surface; new tools / new args only
- mypy --strict + ruff stay non-negotiable

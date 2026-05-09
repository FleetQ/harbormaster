# Sprint Retro — Harbormaster v1.0.0a17

**Date:** 2026-05-09
**Theme:** v1.2 phase 1 shipped. The `recall_qa` MCP tool, a per-host
sqlite-vec / FTS5 store, and the `_maybe_record_qa` hook turn every
successful `ask_project` / `delegate_task` call into a permanent
trajectory the next session can recall. First step toward dropping
the `a` suffix and tagging `v1.0.0` GA.

## What landed

### `harbormaster` (this repo)

| SHA | Subject |
|-----|---------|
| (squash) | feat(history): Q&A history with semantic recall (v1.2 phase 1) (#11) |

## Capabilities (this sprint)

### 1 · Q&A history store (v1.2 phase 1, item #1 from a16 retro)

New `harbormaster.history` package: per-host sqlite db at
`~/.harbormaster/qa_<host>.db` with one base `qa_log` table and two
auxiliary indexes that share it. The store decides at runtime which
recall path to use based on whether the configured embedding backend
returns a vector or `None`:

- **vec0** — sqlite-vec virtual table, cosine similarity over the
  question embedding. Active when `[history] embedding_backend =
  "fastembed"` and the `[history]` extra is installed.
- **FTS5** — bm25 lexical recall, normalized to `1 / (1 + |bm25|)`
  for a 0..1ish score. Active as fallback when sqlite-vec or
  fastembed are missing, OR when the operator explicitly picks
  `[history] embedding_backend = "fts5"`.

Wire shape for `recall_qa`:

```json
{
  "enabled": true,
  "backend": "fastembed" | "fts5",
  "host": "local",
  "matches": [
    {
      "id": 42,
      "question": "How does authentication work?",
      "answer": "JWT-based, see auth.md",
      "project": "myapp",
      "host": "local",
      "tool": "ask_project",
      "created_at": 1746780000,
      "score": 0.91,
      "recall_count": 3
    }
  ]
}
```

### 2 · `_maybe_record_qa` hook in `run_backend`

Mirrors a16's `_maybe_writeback_to_fleetq`: same three-gate opt-in,
same fire-and-forget semantics, same name-conventional `_maybe_*`
prefix. Sits next to the FleetQ writeback in `tools/_helpers.run_backend`
so both write paths are visible together.

Three gates:
1. `[history] enabled = true` (default false)
2. Per-tool `[history] log_<tool> = true` (default true) — operators
   can silence noisy tools individually
3. `harbormaster.history` import succeeds (base sqlite is enough; the
   extension is optional)

### 3 · Default fastembed backend (BAAI/bge-small-en-v1.5)

Picked over the OpenAI / FTS5-only options because: $0 per call, no
API key in the env, no network round-trip in the hot path, ~50MB
model downloads once and caches under the user's HuggingFace cache.
384-dim output matches the schema's `vec0` column. fastembed is in
the optional `[history]` extra; the store falls back to FTS5 silently
when it's missing.

### 4 · Retention policy

`prune(retain_recent_k, retain_top_recalled_r)` runs after every
insert. Keeps the union of:

- the K most recent rows by `created_at` (default 1000)
- the R most-recalled rows by `recall_count` (default 100)

Long-tail "this question keeps coming up" stays alive even when it
falls off the recency window. Cleans the matching rows from `qa_vec`
when the vec track is active.

## Real numbers

- 1/3 v1.0.0a16 retro action items shipped (item #1)
- 1 PR opened, merged (#11)
- 44 new tests across 5 new test files (test_history_schema,
  test_history_store, test_history_embed, test_history_writeback,
  test_recall_tool); test_tools.py extended for the new tool's
  registration
- Test suite delta: 257 → 301 passed on harbormaster (1 skip)
- ruff clean, mypy --strict clean across 32 source files (was 27)
- 0 backward-incompatible changes

## What worked

- **Mirroring a16's `_maybe_writeback_to_fleetq` pattern verbatim
  for `_maybe_record_qa`.** Same three-gate opt-in, same
  fire-and-forget semantics, same prefix. Reviewers can grep one
  pattern and find both write paths. The next domain that wants a
  best-effort hook gets a third instance for free.
- **Schema + Store separation.** `connect()` returns
  `(conn, vec_loaded)` and `ensure_schema(conn, vec_loaded=...)`
  takes the flag explicitly. No magic attribute on the
  `sqlite3.Connection`, no monkey-patched state to stash. Tests can
  exercise either track without wrestling with the loader.
- **Stub vec backend in tests.** `StubVecBackend` deterministically
  encodes strings into a length-4 vector by counting `'a'..'d'` —
  fast, offline, and exercises the actual sqlite-vec ANN path
  without pulling fastembed's ONNX model into unit tests. The model
  itself is only smoke-tested at integration time.
- **Falling back instead of failing.** `get_embedding_backend()`
  silently returns `FTS5Backend` when fastembed isn't installed.
  Operators who skip the `[history]` extra still get lexical recall,
  not a 500.

## What to change / next

- **No live fastembed integration test.** The unit tests stub the
  embedding backend to keep CI fast. We don't actually verify that
  `BAAI/bge-small-en-v1.5` returns a 384-dim vector at runtime — if
  fastembed changes the default model output dim, we'd find out only
  in production. Worth adding a slow-marked test that downloads the
  model once and asserts `len(encode("hello")) == 384`.
- **Per-host db files, no aggregation yet.** A query against `friday`
  doesn't see `local` history and vice versa. This is intentional
  for phase 1 (semantically different state) but the lack of a
  cross-host view will bite when users have 3+ hosts. Phase 4 work.
- **Retention runs synchronously after every insert.** For now the
  insert + prune round-trip is < 5ms, so cheap. If write volume goes
  up enough to matter, switch to "prune every Nth insert" or move it
  into a background task.
- **No metric on recall hit rate.** We bump `recall_count` but don't
  surface it anywhere — no dashboard, no log line, no FleetQ write.
  Future surface: a `harbormaster-mcp stats` subcommand or a
  Live UI panel.

## Action items for the next sprint (v1.0.0a18 / week 18)

1. **Federated KG via FleetQ KnowledgeGraph (v1.2 phase 2).**
   Builds on a16's Memory writeback + a17's history store. Same
   opt-in gates plus a separate `[fleetq] write_kg = true`. Decision
   needed: extract entity-relation triples server-side (cheaper
   round-trip) or post raw text and let FleetQ extract (cleaner
   separation). Likely needs `harbormaster.fleetq.kg.KGWriter`
   mirroring `MemoryWriter`.
2. **Auto project graph (v1.2 phase 3).** Per project, parse
   `composer.json` / `package.json` / `pyproject.toml` / `Cargo.toml`
   / `go.mod`. Extract direct deps + names. Surface in Live UI as a
   Mermaid graph. No LLM, no FleetQ — pure file parsing.
3. **Slow-marked fastembed integration test.** Asserts
   `BAAI/bge-small-en-v1.5` still returns 384-dim vectors. Gated
   behind a `--run-slow` pytest flag so CI can opt in once per release.
4. **`harbormaster-mcp stats` subcommand.** Reads each per-host
   db, reports counts + most-recalled rows + oldest entry. First
   surface for the recall-count metric we already write.

## Out-of-scope (still)

- Backends other than Claude — wait for first user request.
- Plugin / extensions API — v2.
- Tauri / Electron native UI wrapper — post-v1.2.
- Relay-binary path (Path B) — explicitly skipped in favour of Path C.
- Per-token streaming through the relay-mode bridge.
- `fan_out_ask` chunk streaming — design doc filed; await user
  feedback.
- Cross-session memory recall — v1.2 phase 4 (depends on KG +
  Q&A history, both still landing).
- Cross-host recall aggregation — phase 4 territory.
- Embedding upgrade-in-place (changing `embedding_dim`) — fresh db
  required today; no migration tool ships.

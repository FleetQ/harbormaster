# Sprint Retro — Harbormaster v1.0.0a19

**Date:** 2026-05-09
**Theme:** v1.2 phase 2 shipped. The `_maybe_extract_and_writeback_kg`
hook + `harbormaster.fleetq.kg.KGWriter` post heuristic
subject—predicate—object triples to FleetQ's existing `/api/v1/memory`
endpoint with a `type: "kg_triple"` discriminator. Last of the three
parallel-shipped v1.2 phases (1 + 2 + 3 all done); only phase 4
(cross-session memory recall) remains for `v1.0.0` GA.

## What landed

### `harbormaster` (this repo)

| SHA | Subject |
|-----|---------|
| (squash) | feat(fleetq): KG triple writeback via heuristic extraction (v1.2 phase 2) (#13) |

## Capabilities (this sprint)

### 1 · Heuristic triple extraction (v1.2 phase 2, item #1 from a18 retro)

`harbormaster.fleetq.triples` ships three extractors, each tagged with
a confidence score so downstream consumers can filter the noise:

| Predicate | Source pattern | Confidence |
|-----------|----------------|------------|
| `mentions` | A known project name appears as a token (composer-style `vendor/pkg` aliased to bare `pkg`) | 0.6 |
| `uses` | "uses the X library" / "depends on X" / "requires X" / "built on X" | 0.55 |
| `exposes` | HTTP-method-prefixed paths: "GET /api/foo" / "POST /v1/bar" | 0.7 |

Why heuristic, not LLM-based: the cost-per-call must be near-zero so
this can run on every successful tool invocation. An LLM call would
double our `claude -p` spend per `ask_project`. The triples are
noisy but durable — better than nothing, and a future v2
LLM-extraction phase can re-process the trajectory text post-hoc.

`extract_all(answer, source_project, known_projects, max_triples=50)`
runs all three and caps the total. Order: mentions first (cheapest +
broadest), then uses, then exposes — so the cap drops higher-noise
triples first when the answer is dense.

### 2 · `KGWriter` mirror of `MemoryWriter`

`harbormaster.fleetq.kg.KGWriter` is a sync httpx wrapper that posts
single triples or batches. Constructed once per process, reused
across calls. Wire shape extends the existing `/api/v1/memory`
endpoint with a `type: "kg_triple"` discriminator — no new FleetQ
endpoint required for the first cut. The discriminator gives FleetQ
a clear classifier when KG-aware processing eventually ships.

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

`write_triples()` continues past individual failures so a single bad
triple doesn't blackhole the rest of the batch.

### 3 · `_maybe_extract_and_writeback_kg` hook in `run_backend`

Sits next to a16's `_maybe_writeback_to_fleetq` and a17's
`_maybe_record_qa` in `tools/_helpers.run_backend`. Same fire-and-
forget semantics: failures inside extraction or POST are logged at
WARNING and never propagate to the user-facing tool call.

Three-gate opt-in (mirrors the trajectory writeback pattern):

1. `[fleetq] enabled = true`
2. `[fleetq] write_kg = true` (default `false` — separate from
   `write_trajectories` so operators can ship trajectories without
   the noisier triple stream)
3. The `FLEETQ_API_TOKEN` env var must be non-empty.

`[fleetq] kg_max_triples_per_call` (default 50) bounds per-call
writeback cost.

### 4 · `Triple` dataclass with `obj` field

Stored as `obj` (not `object`) to avoid mypy --strict's
`object`-as-type confusion. Wire shape uses canonical RDF `"object"`
key via `as_dict()` rename. Non-obvious tradeoff captured in the
docstring so future contributors don't try to "fix" it back.

## Real numbers

- 1/3 v1.0.0a18 retro action items shipped (item #1)
- 1 PR opened, merged (#13)
- 33 new tests across 3 new test files (test_kg_writer,
  test_triples, test_kg_writeback)
- Test suite delta: 348 → 381 passed on harbormaster (1 skip)
- ruff clean, mypy --strict clean across 39 source files (was 37)
- 0 backward-incompatible changes
- 1 merge conflict resolved (architecture-harbormaster.md §18 numbering;
  both phase 2 and phase 3 added a §18 in parallel)

## What worked

- **Three-hook parade in `run_backend`.** `_maybe_writeback_to_fleetq`
  + `_maybe_record_qa` + `_maybe_extract_and_writeback_kg` all sit in
  the same function with identical semantics: gate, attempt, swallow,
  return. Reading the code from top to bottom, you see exactly which
  side-effects fire on success without surprises. The `_maybe_*`
  prefix convention from a16 carried through cleanly.
- **Discriminator-on-existing-endpoint over new endpoint.** Picking
  `type: "kg_triple"` as a discriminator on `/api/v1/memory` instead
  of waiting for a new `/api/v1/knowledge-graph` endpoint means this
  PR is independent of the FleetQ release cycle. Triples land as
  opaque records until FleetQ ships KG-aware processing — still
  durable, still useful.
- **Confidence scores on every triple.** Heuristic extractors are
  noisy; tagging each triple with a 0..1 score lets downstream
  consumers filter without re-extraction. `mentions` at 0.6,
  `uses` at 0.55, `exposes` at 0.7 — calibrated by hand from the
  test corpus, ready to be tuned later when we have real recall data.
- **Parallel branch development for phase 2 + 3.** Both PRs opened
  same day, branched from the same `main`. Merged in sequence with
  one conflict on `architecture-harbormaster.md §18` numbering —
  resolved by promoting graph to §18 (first to merge) and KG to §19.

## What to change / next

- **`obj` field name leaks the mypy workaround into the API.** Users
  constructing `Triple(subject=..., predicate=..., obj=...)` see the
  mypy-friendly name, not the canonical RDF `object`. The wire shape
  uses `"object"` correctly via `as_dict()`, but the Python API is
  off-by-one. Future option: a `__init__` keyword alias so both
  `obj=` and `object_=` work; pick whichever feels least surprising.
- **No deduplication across calls.** A triple posted twice from two
  trajectories lands twice in FleetQ. Fine for now (FleetQ-side
  concern), but worth a client-side "have I seen this triple
  recently?" cache once we have data on real-world dup rates.
- **`mentions` extractor is broad.** Any token matching a known
  project name fires a triple. False positives on common words that
  happen to match short project names ("pricex" mentioned in a
  comparison context still triggers `mentions` even when the project
  isn't actually being discussed). The 0.6 confidence is a hint;
  downstream consumers should filter aggressively until we have
  better signal.
- **No live KG smoke test in CI.** `smoke-fleetq` exercises the
  trajectory writeback path; it doesn't yet POST a triple and assert
  round-trip. Worth extending — POST a `type: "kg_triple"`, GET it
  back via `/api/v1/memory/search?type=kg_triple`, assert wire shape.

## Action items for the next sprint (v1.0.0a20 / week 20)

1. **Cross-session memory recall (v1.2 phase 4).** The last phase
   between current state and `v1.0.0` GA. The `claude -p` prompt
   builder (in `tools/_helpers` or a new `tools/_prompt.py`) gets a
   new "Prior context" section prepended with the top-3
   `recall_qa` matches + relevant KG triples. Cap recall context at
   2k tokens; trim oldest. Auto-grounds the subagent in past answers
   without manual context loading.
2. **Live KG smoke in CI.** Extend `smoke-fleetq` with a triple
   round-trip assertion. Gated, runs only when `FLEETQ_API_TOKEN`
   secret is set.
3. **Dashboard Mermaid widget for `/api/graph`.** Action item from
   a18 retro — render the graph data as a collapsible section on
   `/`. Mermaid via the existing CDN-loaded bundle.
4. **`harbormaster-mcp stats` subcommand.** From a17's deferred list:
   reads each per-host db, reports counts + most-recalled rows +
   oldest entry. First surface for the recall-count metric we
   already write.

## Out-of-scope (still)

- Backends other than Claude.
- Plugin / extensions API.
- Tauri / Electron native UI wrapper.
- Relay-binary path (Path B) — explicitly skipped.
- Per-token streaming through the relay-mode bridge.
- LLM-based triple extraction — heuristics ship now; LLM sweep is v2.
- Triple deduplication across calls — FleetQ-side concern (or future
  client-side cache).
- `calls` predicate (project-A invokes project-B over RPC) — needs
  richer signal than free-text mention.
- Cross-host triple aggregation — local-only writes today; FleetQ
  side aggregates across all harbormasters reporting to it.
- Cross-host recall aggregation — phase 4 territory.
- Embedding upgrade-in-place — fresh db required today.

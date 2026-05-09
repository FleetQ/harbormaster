# Sprint Retro — Harbormaster v2.0.0a5

**Date:** 2026-05-09
**Theme:** LLM-based triple extraction. Operators can now choose
between cheap regex heuristics, prompt-based extraction, or both —
controlled by a single `[fleetq] kg_extractor` config field.

## What landed

### `harbormaster` (this repo)

| SHA | Subject |
|-----|---------|
| (squash) | feat(fleetq): LLM-based triple extraction (v2.0.0a5) (#19) |

## Capabilities (this sprint)

### 1 · `extract_via_llm()` orchestrator

```python
def extract_via_llm(
    *, answer: str, source_project: str,
    backend: Backend, cwd: Path, max_triples: int = 20,
) -> list[Triple]: ...
```

One backend call per answer. Builds a structured prompt asking for a
JSON array of `(subject, predicate, object, confidence)` records. The
parser then converts that array into the same `Triple` dataclass the
heuristic extractor produces — KGWriter sees a uniform shape.

### 2 · Robust JSON parsing

Real-world LLM output rarely matches the ideal "JSON array, no
prose, no fences" instruction. The parser tolerates:

- ```json …``` markdown fences (with or without language tag)
- Leading prose ("Sure, here you go: [...]")
- Bracket-aware scanner that doesn't choke on `[` inside JSON strings
- Both `"object"` (canonical) and `"obj"` (dataclass-name autofill) keys
- Confidence values clamped to `[0, 1]`
- Missing confidence → defaults to 0.7
- Missing subject → falls back to `source_project`
- Malformed individual records dropped; the rest survive

Top-level non-array, JSON parse error, or missing `[` → empty list +
WARNING log.

### 3 · `[fleetq] kg_extractor` mode toggle

```toml
[fleetq]
kg_extractor = "heuristic"  # default — free, regex-only
# kg_extractor = "llm"      # one extra ask_local() per answer
# kg_extractor = "both"     # run both; merge by (s,p,o); keep highest confidence
kg_llm_max_triples = 20     # cap on LLM-extracted triples per call
```

Default is `"heuristic"` so v1.2 behaviour persists for every existing
deployment. `"both"` mode dedups by `(subject, predicate, object)`
tuple and keeps the higher-confidence variant — usually the LLM's.

### 4 · Local-only LLM extraction

Remote `host` argument skips the LLM path entirely (regardless of
`kg_extractor`). The SSH round trip per call would double the
remote-execution latency. v2.0.0a5 deliberately limits the LLM
extractor to local backends; future work could add a remote variant if
the cost is justified for specific workloads.

### 5 · Per-call dedup + cap

```python
deduped: dict[tuple[str, str, str], Triple] = {}
for t in triples:
    key = (t.subject, t.predicate, t.obj)
    if (existing := deduped.get(key)) is None or t.confidence > existing.confidence:
        deduped[key] = t
triples = list(deduped.values())[: kg_max_triples_per_call]
```

`kg_max_triples_per_call` (existing v1.2 setting) still bounds the
final writeback in addition to the new `kg_llm_max_triples` cap on the
LLM batch.

## Real numbers

- 1/1 previous-sprint retro action items shipped (item 1 — LLM triple extraction)
- 1 PR opened / merged (#19)
- 23 new unit tests in `test_triples_llm.py`
- Test suite: 470 → 493 pass, 1 skip
- mypy --strict: 44 → 45 source files, clean
- ruff: clean
- Backwards-incompatible changes: 0 (`kg_extractor = "heuristic"` is default)
- Lines changed: +527 / -6

## What worked

- **Bracket-aware scanner over regex.** The first prototype tried a
  greedy `[.*\]` regex; it choked on JSON strings containing `]`. The
  current scanner counts depth + tracks string state, which handles
  any well-formed JSON the model emits. ~12 lines of code.

- **Tolerate `obj` alongside `object`.** When tests started
  mocking the LLM output, two of them used `"obj"` because that's the
  Python dataclass field name they were copy-pasting from. Real LLMs
  do the same. Allowing both alias keys was a one-line change that
  made the parser meaningfully more robust.

- **"both" mode without separate writeback paths.** Both extractors
  return `list[Triple]`, so dedup runs on the union and KGWriter
  doesn't notice the difference. Keeping the wire shape uniform across
  extractors meant the addition was purely upstream of the writer.

- **`extract_via_llm` short-circuits on short answers.** Early return
  before the backend call saves cost on trivial trajectories. The
  threshold (8 chars) matches the existing
  `_maybe_extract_and_writeback_kg` guard, so heuristic + LLM agree on
  what's "long enough to extract from."

## What to change / next

- **No CI smoke for `kg_extractor = "llm"`.** The smoke matrix runs
  with `[fleetq] enabled = false`, so the LLM path isn't exercised end
  to end. A test that pipes a fake backend through the dispatcher
  would catch wiring regressions.

- **No model-side budget.** `kg_llm_max_triples = 20` instructs the
  prompt + truncates the response, but doesn't bound the prompt-side
  token cost (a 50KB answer becomes a 50KB prompt). Add a
  `kg_llm_input_chars` cap that truncates the answer before
  prompt construction.

- **No retry on parse failure.** If the LLM returns a malformed array,
  we log + drop. A single retry with a "your previous response was
  malformed" suffix could rescue many cases. Defer until somebody
  reports it.

## Action items for the next sprint (v2.0.0a6)

1. **Cross-host recall aggregation.** `recall_qa(host="all")` should
   fan out across configured `[hosts.*]` per-host stores in parallel,
   merge by score, cap at top-K across hosts. Per-host SSH fetch reuses
   the streaming infra. Tests with two stub hosts.

## Out-of-scope (still)

- Tauri / Electron desktop UI wrapper — too big, no demand.
- Relay-binary path (Path B) — Path C HTTP tunnel covers the use case.
- Remote LLM extraction — SSH per-call cost not justified yet.
- Triple extraction from streaming partial answers — extraction runs
  on the final answer string only.

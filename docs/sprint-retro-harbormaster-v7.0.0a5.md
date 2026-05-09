# Sprint Retro — Harbormaster v7.0.0a5

**Date:** 2026-05-09
**Theme:** Scriptability. Make `harbormaster-mcp dispatcher status`
machine-readable so operators can pipe it through `jq` and assert
in shell scripts. Pure additive flag, zero behaviour change without it.

## What landed

### `harbormaster` (this repo)

| SHA | Subject |
|-----|---------|
| `0219019` | feat(cli): --json output for harbormaster-mcp dispatcher status |

## Capabilities (this sprint)

### 1 · `harbormaster-mcp dispatcher status --json`

Wire shape:

```
$ harbormaster-mcp dispatcher status --json
{"dispatcher_max_workers":1,"effective_parallel_set":[...],
 "safe_for_parallel":[...],"single_worker":true,"unsafe_tools":[]}
```

JSON object schema (sorted keys, single line — `head -1 | jq` friendly):

  - `dispatcher_max_workers`: int
  - `single_worker`: bool (true when max_workers ≤ 1)
  - `safe_for_parallel`: list[str], sorted
  - `unsafe_tools`: list[{name, in_allowlist}], sorted by name
  - `effective_parallel_set`: list[str], sorted (= safe − unsafe)

The text format is preserved byte-for-byte; the `--json` flag is the
only behaviour change. Tests assert both the JSON schema and that
the text output is unaffected.

### 2 · Refactor: `_status_payload` shared between text + JSON paths

Both code paths now build the same dict (typed, sorted, deterministic)
and the text formatter consumes that dict instead of the config object.
This guarantees the two outputs stay in lockstep — a future schema
addition that lands in JSON will surface in text too (or fail loudly
when the formatter doesn't know the new key).

## Real numbers

- 1/1 v7.0.0a5 phase action items shipped (with documented scope
  deviation — see below)
- 1 feature branch merged (no PR)
- 4 new unit tests (750 → 754 collected; +0 source files, refactor of
  the existing `dispatcher_cli.py`)
- mypy --strict + ruff: clean (51 source files unchanged)
- Backwards-incompatible changes: 0 (text output verified
  byte-for-byte stable)

## What worked

- **Shared payload function tested independently of formatters.** The
  text-output regression test (`test_dispatcher_status_text_output_
  unchanged_without_json_flag`) caught a refactor mistake I almost
  made — moving the "single-worker" hint from above to below the
  worker count would have changed text output unnoticed.
- **Schema documented in code, not just in docs.** `_status_payload`'s
  docstring is the canonical schema reference. Operators reading the
  source see exactly what fields exist and which are sorted.

## What to change / next

- **Scope deviation, recorded.** The v7 plan called for runtime
  metrics (running/active_workers/queue_depth/last_dispatched_at).
  The dispatcher is in-process and stateless from the CLI's
  perspective — those metrics would require a sidecar metrics
  endpoint that doesn't exist. Adding one is non-trivial (process-
  shared queue, lifecycle ownership). Shipped the introspective
  shape only; runtime metrics deferred to v8 candidates.

## Action items for the next sprint (v7.0.0a6)

1. **Language badge on dashboard cards + ManifestCache.** Read
   `ProjectInfo.language` (added in v6.0.0a3), render a colored
   badge on each project card. Add a 60s mtime-keyed memoization
   cache for `/api/projects` to avoid re-walking the project tree
   on every dashboard refresh.

## Out-of-scope (still)

- Live worker pool metrics — needs a sidecar / process-shared queue
  that doesn't exist today. Worth shipping as its own v8 phase
  alongside any other "expose runtime state to operators" work.
- Schema versioning for the JSON output — at one field set this
  feels like premature engineering. Add `schema_version` if and
  when we make a breaking shape change.

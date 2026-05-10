# Sprint Retro — Harbormaster v12.0.0a1

**Theme:** Codex backend token instrumentation — closes the v11.0.0a5
deviation (only `claude.py` was instrumented; codex was left to the
chunk-count approximation fallback in `_emit_chunks_then_result`).

## What shipped

### Backend (`src/harbormaster/backends/`)

- **Lift `StreamUsage` + `_StreamWithUsage` from `claude.py` into `base.py`.**
  Both backends now share one dataclass + wrapper. The SSE `usage`
  emitter still does duck-typed access on `.usage.has_real_usage` —
  no caller change required.
- **Re-export from `claude.py`.** Tests and any external callers that
  imported these names from the claude module continue to work; the
  symbols are identity-equal (`Base.StreamUsage is Claude.StreamUsage`).
- **Add `ask_local_stream` + `ask_remote_stream` to `CodexBackend`.**
  Codex CLI emits plain text on stdout (no `--output-format
  stream-json` equivalent), so the new streams yield each non-empty
  stdout line as a delta and reuse the existing `_StreamWithUsage`
  wrapper.
- **Soft-fall extraction.** `_absorb_optional_usage_line` parses each
  stdout line; if it's a JSON object whose top-level OR
  `message.usage` block contains recognised token keys, it's absorbed
  into `StreamUsage` and **not** yielded as text. Arbitrary JSON
  answers (a model returning structured output) stay visible.
- **Dispatcher-compatibility.** `tools/_helpers.py` already gates
  streaming on `hasattr(backend, "ask_local_stream")`. Codex now
  passes the gate without any change to `_helpers.py`. Per-project
  `[backends_for_project]` overrides routing codex to a project will
  now actually stream instead of raising
  `BackendError(code="config_error")`.

### SSE event (`src/harbormaster/ui/routes.py`)

No change. The existing v11.0.0a5 emitter handles the codex case
correctly because:

- When codex's stdout contains no usage JSON →
  `usage.has_real_usage` stays False → emitter falls back to
  chunk-count approximation with `approximate: true` (v9 contract).
- When a future codex wrapper does emit a JSON usage record → the
  existing branch picks it up and DROPS `approximate`.

## Tests

| Suite delta                                    | Before | After |
|------------------------------------------------|-------:|------:|
| Total tests                                    | 1207   | 1225  |
| New (`tests/backends/test_codex_token_usage.py`) | —      |   +18 |

Coverage:

- `_absorb_optional_usage_line` decision matrix:
  - plain text → returns False
  - non-JSON garbage → returns False
  - JSON without usage keys → returns False (stays visible)
  - JSON with top-level `usage` → returns True, absorbed
  - JSON with nested `message.usage` (assistant-shape) → returns True
  - top-level array → returns False
- `ask_local_stream`:
  - yields stdout lines as deltas
  - absorbs usage-JSON lines (drops them from text stream)
  - passes arbitrary JSON answers through unchanged
  - `FileNotFoundError` → `BackendError(code='exit_nonzero')`
  - non-zero exit → `BackendError(code='exit_nonzero')`
- `ask_remote_stream`:
  - yields stdout lines as deltas over SSH
  - rc=255 maps to `BackendError(code='ssh_error')`
- SSE integration:
  - codex stream with no usage → SSE `usage` event has
    `approximate: true` and chunk counts
  - codex stream with real usage → SSE `usage` event drops
    `approximate` and carries `input_tokens` / `output_tokens` / `model`
- Smoke:
  - `hasattr(backend, "ask_local_stream")` now True for codex (closes
    the v11.0.0a5 deviation)
  - `Base.StreamUsage is Claude.StreamUsage` (back-compat re-export
    preserves identity)

## Quality gates

```
mypy --strict src/harbormaster   →  Success: no issues found in 56 source files
ruff check src tests              →  All checks passed!
pytest -q                         →  1225 passed, 2 skipped in 38.32s
```

## Architecture notes

- **Why lift to `base.py` instead of duplicating in `codex.py`?**
  The duck-typed contract is `getattr(stream, "usage", None)` plus
  `usage.has_real_usage`. Sharing the dataclass guarantees those
  field names stay stable across both backends. Future backends
  (aider, gemini-cli, llama-server) implement the same contract
  without re-defining the shape.
- **Why soft-fall instead of insisting on real numbers?** Codex's
  CLI doesn't currently emit token metadata. The chunk-count
  approximation has been the live behaviour since v9; preserving
  it (with `approximate: true`) lets dashboards keep their existing
  rendering logic and operators get progress feedback even though
  it's not exact. When/if codex adds token metadata, the same code
  path will pick it up automatically.
- **Why parse JSON in the line loop?** Lazy: only one `json.loads`
  call per line, fast-pathed by checking `stripped[0] in "{["` first.
  Lines that don't start with `{` or `[` skip the parse entirely.

## Deviations

None. Phase scope matched plan exactly.

## Next

Phase 2 — complete `stateBadge` migration (statusStrip + reembedPanel
+ trajectoryList still use legacy helper).

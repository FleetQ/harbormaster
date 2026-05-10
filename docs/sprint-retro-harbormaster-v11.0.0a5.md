# Sprint Retro — Harbormaster v11.0.0a5

**Theme:** Backend-side token counter instrumentation. Closes the
v9.0.0a5 deviation: the SSE `usage` event was approximating
`output_tokens` as the chunk count.

## What shipped

### Backend (`src/harbormaster/backends/claude.py`)

- `StreamUsage` dataclass — tracks `input_tokens`, `output_tokens`,
  `cache_creation_input_tokens`, `cache_read_input_tokens`, `model`,
  plus a `has_real_usage` flag that distinguishes "backend reported
  zero" from "backend never emitted a usage block".
- `merge_message_usage()` accepts both shapes:
  - `assistant` lines: usage nested under `message.usage`
  - `result` summary line: top-level `usage` block (authoritative
    final tally — overrides interim assistant snapshots).
- `_StreamWithUsage(Iterator[str])` — a thin wrapper that exposes
  `.usage` as a side-channel while passing text deltas through
  transparently. Existing callers iterate as before; new callers do
  `getattr(stream, "usage", None)`.
- `ask_local_stream` + `ask_remote_stream` restructured to feed an
  inner generator into `_StreamWithUsage`. `_extract_assistant_text`
  gained an optional `usage=` kwarg; default-None preserves the v10
  contract for any external caller.

### SSE event (`src/harbormaster/ui/routes.py`)

- `_emit_chunks_then_result` reads `getattr(sync_iter, "usage", None)`.
- When `.usage.has_real_usage is True`: emit `input_tokens`,
  `output_tokens`, `cache_*`, `model`, plus the legacy
  `output_chunks`/`output_chars`. **Drops** the `approximate: true`
  flag — closes the v9.0.0a5 deviation.
- When the iterator has no `.usage` attr (older deploy / non-claude
  backend) OR `has_real_usage` is False: fall back to the v9
  chunk-count approximation with `approximate=true` unchanged.

## Tests

| Suite delta                                | Before | After |
|--------------------------------------------|-------:|------:|
| Total tests                                | 1165   | 1181  |
| New (test_backend_token_usage.py)          | —      |   +16 |

Coverage:
- `StreamUsage` defaults / absorb assistant block / absorb result
  summary / later-message-overrides-earlier / silent-on-non-usage
- `_StreamWithUsage` iterates text + exposes `.usage`
- `_extract_assistant_text` feeds usage from assistant + result lines
- backwards-compat: kwarg-less call still yields just text
- SSE `usage` event with real backend metadata: real fields present,
  no `approximate` flag
- SSE `usage` event with bare iterator: approximation path runs
- SSE `usage` event with `has_real_usage=False`: still approximates
- `make_local_backend_stream` signature unchanged (kwarg contract
  preserved)
- routes.py source confirms v11.0.0a5 doc-string + retains `approximate`
  branch for the fallback

## Quality gates

```
mypy --strict src/harbormaster   →  Success: no issues found in 56 source files
ruff check src tests              →  All checks passed!
pytest -q                         →  1181 passed, 2 skipped in 38.16s
```

## Architecture notes

- The wrapper-iterator pattern preserves the existing `Iterator[str]`
  type contract — no `Iterator[str | UsageEvent]` discriminated-union
  refactor was needed. Callers who don't care about usage continue
  working unchanged.
- `merge_message_usage` is "set-on-encounter": each new message
  overrides the previous values. This matches the `claude
  --output-format stream-json` semantic where each assistant message
  reports a snapshot of cumulative usage; the final `result` line is
  authoritative.
- The fallback branch (chunk-count approximation) is preserved so
  fan-out / heartbeat-path tools that route through `_dispatch_mcp`
  rather than the streaming dispatcher still get a usage event with
  the legacy shape. Operators can rely on the event always being
  emitted, just `approximate: true` when the backend doesn't carry
  metadata.

## Deviations

- Codex backend (`backends/codex.py`) NOT updated. It would need its
  own usage-extraction logic that mirrors the OpenAI Codex output
  format. Recorded as v12 candidate `codex-backend-token-usage`.

## Next

Phase 6 — caches consolidation (ignored-projects memo,
chatOrder() reverse cache, /api/network/stats summary endpoint).

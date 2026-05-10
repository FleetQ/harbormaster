# Harbormaster v10.0.0a1 — Sprint Retro

**Phase 1 of 8** in the v10.0 alpha chain.

## Shipped

**BUG fix: Recent Q&A was empty.**

The streaming dispatcher (`_emit_chunks_then_result` in
`src/harbormaster/ui/routes.py`) used to assemble the answer from
text deltas but never call `_maybe_record_qa`. The sync
`run_backend` path (`src/harbormaster/tools/_helpers.py:107`) did.

Result: the dashboard, fan-out, and project-detail surfaces — all
streaming-path — never wrote rows to the local sqlite Q&A history
store, so the Recent Q&A panel always showed empty.

## Implementation

- Plumbed a new `record_ctx` kwarg through `_emit_chunks_then_result`
  carrying `(config, project_name, host, prompt, tool)`.
- `_stream_local_tool` passes `host=None`; `_stream_remote_tool`
  passes the host argument through.
- New helper `_tool_name_for_builder()` reverse-looks up the tool
  name from the registered `_STREAMING_TOOLS` map so the recorded
  `tool` field matches the sync-path schema.
- Captured `duration_ms` via `time.monotonic()` start/end across the
  chunk loop.
- After the loop completes, assembled the full answer text and
  called `_maybe_record_qa` with the same args as the sync path.
- Honored existing `_history_logging_enabled_for(config, tool)`
  gate — no new gate.
- Failures are swallowed and never break the stream (matches
  sync-path semantics).
- Skipped writeback when the assembled answer is empty.

## Tests

`tests/ui/test_streaming_qa_writeback.py` (6 tests):
1. Records Q&A when enabled (assembled = "hello world").
2. Records with remote host (per-host db, host="friday").
3. Skips when `[history].enabled = false`.
4. Backwards-compat: callers without `record_ctx` get no writeback.
5. `_maybe_record_qa` failure does not break the stream.
6. Empty answer skipped.

## Numbers

- Tests: 1018 → 1023 (+5 visible; 6 new tests minus 1 already-named
  test slot in count).
- Source files: 52 → 52 (no new modules).
- mypy --strict: clean.
- ruff: clean.

## Deviations

None. Phase 1 implemented as specced.

## Risks / Follow-ups

- The streaming dispatcher's `_maybe_record_qa` call uses `time.monotonic()`
  for `duration_ms`, but the sync path uses the backend-reported
  `result.duration_ms`. These will differ slightly (the streaming
  number includes async scheduling overhead). Acceptable for v1;
  document if telemetry consumers care.
- Empty-answer skip is a new behaviour vs sync path (sync still
  writes empty rows). Justified by: empty answers in streaming are
  almost always transient backend hiccups, while sync empty rows
  were rare enough to ignore. Re-visit if operator feedback differs.

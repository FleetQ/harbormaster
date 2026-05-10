# Harbormaster v10.0.0a2 — Sprint Retro

**Phase 2 of 8** in the v10.0 alpha chain.

## Shipped

**BREAKING: removed legacy `chunk` SSE event.**

The streaming dispatcher (`_emit_chunks_then_result`) now emits ONLY
the typed `token` event for text deltas. The legacy `chunk` event,
deprecated in v9.0.0a5, is gone.

## Deprecation timeline

- **v9.0.0a5** — `chunk` deprecated; `token` introduced; both emitted
  side-by-side for one full version. Documented in retro for that
  alpha. Clients given migration window.
- **v10.0.0a2** (this sprint) — `chunk` removed. Migration window:
  one minor version (matches the locked operator decision in
  `harbormaster_autonomous_chain_decisions`).

## Implementation

Server-side (`src/harbormaster/ui/routes.py`):
- `_emit_chunks_then_result` no longer yields `chunk` events.
- One `token` event per text delta with `data = {delta: <str>}`.
- `usage` and `result` envelopes unchanged.

Client-side:
- `_partials/_ask_form_script.html` — dropped the legacy `chunk`
  branch and the `preferTokenEvents` migration flag (no longer
  needed once both events stop being emitted).
- `_partials/delegate_form.html` — migrated its sole `chunk` branch
  to `token` with `data.delta`.

## Tests updated

- `tests/ui/test_typed_sse_events.py` — entire suite rewritten to
  the v10 contract:
  - new ordering: `[token, token, usage, result]`
  - removed all `chunk` assertions
  - added removal sentinels (no `chunk` event in stream, no `chunk`
    branch in JS)
  - added `delegate_form.html` migration assertion
- `tests/ui/test_sse_last_event_id.py` — ordering update.
- `tests/unit/test_ui.py` — three streaming-test assertions
  updated to match new ordering. Renamed test name's "chunk" no
  longer mentioned in expectations; no source-file rename to keep
  blame trail clean.

## Numbers

- Tests: 1023 → 1023 (net 0; replaced 2 stale tests with 2 new
  removal-sentinel tests, kept count stable).
- Source files: 52 → 52.
- mypy --strict: clean.
- ruff: clean.

## Deviations

None. Implemented exactly as planned.

## Risks / Follow-ups

- External MCP clients that built directly against the v9 SSE
  protocol and listened for `chunk` will receive nothing on the
  delta channel. Risk-acceptance from operator decisions
  (backwards-compat cycle: 1 version) — they had v9.0.0a5 →
  v9.0.0 → v10.0.0a1 to migrate.
- `tests/unit/test_relay.py` and `tests/integration/test_dispatcher_stress.py`
  still reference `chunk` — those are about the FleetQ
  `client-relay.chunk` Pusher event (different system), NOT the
  SSE event. Confirmed unrelated.

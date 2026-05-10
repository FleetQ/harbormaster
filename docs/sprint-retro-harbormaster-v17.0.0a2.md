# Sprint Retro — Harbormaster v17.0.0a2

**Date:** 2026-05-10
**Theme:** Codex backend tool_use instrumentation parity — closes
the v16.a6 deviation (only `claude.py` was instrumented).

## What shipped

- `_TOOL_USE_SPANS` per-process registry in `codex.py` (mirror of
  the claude.py constant introduced in v16.a6).
- `_maybe_emit_tool_use_span` / `_maybe_close_tool_result_span`
  helpers — identical signatures + failure semantics to claude.py
  but the span tool name is prefixed `codex.tool:` so operators
  can tell the two backends apart in the v17.a1 waterfall view.
- `_maybe_observe_codex_line` line-level dispatcher: each codex
  stdout line is parsed once, and if it matches a recognised
  tool-call shape the appropriate helper is called. Failures
  swallowed throughout — instrumentation never blocks text.
- Recognised tool-call shapes (any one of):
  - `{"type": "tool_use", "id", "name"}` — Claude-style
  - `{"type": "function_call", "call_id", "name"}` — codex
    `--json` mode (OpenAI Responses API)
  - `{"type": "tool_result", "tool_use_id", "is_error"}` — Claude
  - `{"type": "function_call_output", "call_id"}` — codex `--json`
- `_is_tool_event_line` suppression: tool_use / tool_result JSON
  records are observed for spans but NOT yielded as visible text
  deltas (they're observability metadata, not user text).
- Both `ask_local_stream` and `ask_remote_stream` now do
  observe → absorb-usage → suppress tool-event → yield.

## Non-changes (deliberate)

- `ask_local` / `ask_remote` (non-streaming) untouched — codex's
  default plain-text mode flows through unchanged.
- The dispatcher trace renderer (v17.a1) needs no changes — it
  consumes `recent_completed` rows opaquely and renders any
  `tool` string. The `codex.tool:` prefix is human-facing only.
- The base.py `_StreamWithUsage` shape unchanged — v11.0.0a5
  contract preserved.

## Tests added

`tests/unit/test_v17_codex_tool_use_parity.py` — 11 tests:

1. `test_emit_outside_dispatch_is_noop`
2. `test_emit_inside_dispatch_creates_child_with_codex_prefix` —
   pins the `codex.tool:` prefix.
3. `test_emit_accepts_function_call_shape_with_call_id` —
   OpenAI Responses-API shape via `call_id`.
4. `test_emit_handles_missing_id_gracefully`
5. `test_close_with_unknown_id_is_noop` — both `call_id` and
   `tool_use_id` keyings.
6. `test_observe_routes_function_call_to_emit`
7. `test_observe_routes_claude_style_tool_use`
8. `test_observe_ignores_non_json_lines` — plain text, malformed
   JSON, JSON list, unknown event type, empty.
9. `test_observe_outside_dispatch_is_noop`
10. `test_is_tool_event_line_recognises_all_four_types`
11. `test_is_tool_event_line_rejects_text_and_other_json`

## Numbers

- Tests: 1601 → 1612 (+11)
- Source files: 57 → 57 (extension of existing module)
- mypy --strict + ruff: clean
- Backwards-incompatible changes: 0
- Wall-clock: ~25 min (incl. one redo when an Edit landed on the
  parent's working tree before the worktree branch existed)
- CWD discipline lapses: 0 (the redo wasn't a CWD lapse — it was
  an Edit-before-branch-create timing issue; future phases stay
  on the worktree branch from the start)
- Did NOT touch `.github/workflows/*`: yes

## What worked

- **Mirror, don't invent.** v16.a6's claude.py helpers were the
  template. Copy + rename + adapt the dict-key set + add a
  single dispatcher (`_maybe_observe_codex_line`) — zero design
  churn.
- **Best-effort everywhere.** Every helper swallows exceptions
  and falls back to no-op. The streaming path keeps yielding
  text even if instrumentation crashes.
- **Two-shape recognition.** Accepting both Claude-style and
  OpenAI Responses-style covers every realistic codex output
  variant without special-casing per-version.

## v17 carry-overs (next phases)

3. **N-way reembed compare UI + sparkline integration** — phase 3.
4. **`tightest_cap` KPI hover tooltip** — phase 4.

## Halt assessment

4 candidates remain (3 + #1 operator-blocked CI work). Continue
per operator "continue indefinitely while ≥1 candidate exists"
invariant.

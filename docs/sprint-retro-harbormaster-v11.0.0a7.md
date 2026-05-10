# Sprint Retro — Harbormaster v11.0.0a7

**Theme:** Two proactive guards — async click-handler audit +
per-surface SSE heartbeat tuning. Final polish before v11 GA.

## What shipped

### Async click-handler audit

- `tests/ui/test_async_click_handlers.py` — sister-pattern to v7.0.0a2's
  measure-dependent template safety audit. Walks every template in
  `src/harbormaster/ui/templates/`, identifies Alpine handler
  bindings (`@click`, `@submit`, `@change`, `@input`, `@keydown`,
  `@keyup`), extracts the called factory method name, and confirms
  the matching `async` method either:
  - has its own `try { ... catch (` block in the body, OR
  - is invoked with `.catch(...)` chained on the binding.
- Errors swallowed in browser promises produce ghost UIs (operator
  clicks, nothing happens, no console message). The audit catches
  the structural pattern at template-edit time.
- **Initial scan: zero violations.** Every async method (`createNew`,
  `save`, `toggleHistory`, `loadHistory`, `loadRevision`,
  `copyRevisionToClipboard`, `updatePreview`, etc) already wraps its
  body in try/catch. New violations will fail CI as a hard error
  with a justified-allowlist escape hatch.

### Per-surface SSE heartbeat tuning

- `ServerConfig` gains three fields:
  - `heartbeat_interval_streaming_s` (default 5.0)
  - `heartbeat_interval_network_s`   (default 30.0)
  - `heartbeat_interval_trace_s`     (default 10.0)
- Wires the three SSE surfaces:
  - `_stream_dispatch` (streaming dispatcher) reads
    `config.server.heartbeat_interval_streaming_s` (proxy-keepalive
    critical for long claude-p invocations).
  - `/api/network/stream` reads
    `config.server.heartbeat_interval_network_s` (events are
    infrequent; frequent heartbeats are pure noise).
  - `/api/dispatcher/trace` reads
    `config.server.heartbeat_interval_trace_s` (mid-frequency).
- The legacy module constant `_HEARTBEAT_INTERVAL_S = 5.0` remains
  as a fallback for code paths that don't carry config.
- Operators override per-surface via:
  ```toml
  [server]
  heartbeat_interval_network_s = 60.0
  heartbeat_interval_trace_s = 5.0
  ```

## Tests

| Suite delta                                | Before | After |
|--------------------------------------------|-------:|------:|
| Total tests                                | 1192   | 1207  |
| New (test_async_click_handlers.py)         | —      |    +7 |
| New (test_heartbeat_tuning.py)             | —      |    +8 |

Coverage:
- audit: handler extractor finds `@click`, skips `$dispatch`/`$nextTick`
  /etc, async method extractor + try-catch detector + inline-catch
  detector all proven, full-template scan returns empty
- audit: full pass over current templates returns no violations
- heartbeat: defaults match spec (5s/30s/10s)
- heartbeat: pydantic rejects zero / negative
- heartbeat: full HarbormasterConfig surfaces the values
- heartbeat: source-level confirmation that all 3 routes pull from
  the new config fields
- heartbeat: legacy module constant retained as fallback

The pre-existing `test_mcp_proxy_streams_emits_heartbeat_for_slow_tool`
needed a 1-line update to monkeypatch the new config field
alongside the legacy module constant.

## Quality gates

```
mypy --strict src/harbormaster   →  Success: no issues found in 56 source files
ruff check src tests              →  All checks passed!
pytest -q                         →  1207 passed, 2 skipped in 38.51s
```

## Architecture notes

- Audit is heuristic (template-source string scan, not a JS AST).
  False-positive cases get added to the `ALLOWLIST` frozenset with a
  code-comment justification. This matches the v7.0.0a2 pattern
  exactly — operators understand the format.
- The audit deliberately ignores Alpine magics (`$dispatch`,
  `$nextTick`, `$watch`, `$store`) and JS built-ins (`console`,
  `JSON`, `Math`, etc) so it doesn't generate noise on bindings
  that aren't actually factory-method calls.
- Heartbeat tuning chose `gt=0` validation (positive float) rather
  than allowing zero. Zero would mean a heartbeat every event-loop
  tick — that's never useful and was easy to set by accident.

## Deviations

- None.

## Next

v11.0.0 GA — bump version, write cumulative retro across all 7
alphas, tag, push, verify on PyPI.

# Sprint Retro — Harbormaster v4.0.0a5

**Date:** 2026-05-09
**Theme:** Operators no longer need to remember to run `reembed`
manually after bumping the embedding model. Opt-in auto-runner kicks
off on harbormaster-mcp startup.

## What landed

| SHA | Subject |
|-----|---------|
| (this branch) | feat(history): auto-reembed on drift detection (v4.0.0a5) |

## Capabilities (this sprint)

### 1 · Opt-in `[history] auto_reembed_on_drift`

```toml
[history]
enabled = true
embedding_backend = "fastembed"
fastembed_model = "BAAI/bge-large-en-v1.5"   # bumped from bge-small
auto_reembed_on_drift = true                 # NEW
```

When set, harbormaster-mcp boots a daemon thread that walks every
configured host's per-host store, runs `has_embedding_drift()`, and
calls `reembed()` on the drifted ones — no operator action required.

### 2 · Cross-process state file

Same atomic-tempfile-rename pattern as the v3.0.0a2 bridge state.
File: `~/.harbormaster/reembed-state.json` (override via
`HARBORMASTER_REEMBED_STATE_FILE`). Schema:

```json
{
  "phase": "idle | running | done | failed",
  "processed": 0,
  "total": 0,
  "current_host": "local | <label> | null",
  "started_at": 0.0,
  "finished_at": 0.0,
  "error": "...",
  "writer_pid": 12345
}
```

The UI process reads this via `harbormaster.history.read_reembed_state`
(stable read API).

### 3 · `/api/history/state` endpoint

Wire shape:

```json
{
  "available": true,
  "phase": "running",
  "processed": 1,
  "total": 3,
  "current_host": "friday",
  "started_at": 1715260000.0,
  "finished_at": null,
  "error": null,
  "writer_pid": 12345,
  "auto_reembed_enabled": true
}
```

A future UI panel can render a progress bar from these fields without
shelling out to the CLI.

### 4 · Per-host failure isolation

If one host's store fails to open, the runner records the error in
the runs's `error` field, advances the counter, and continues to the
next host. The final phase is `failed` (with the error string) so an
operator dashboard can surface the partial-success state. This
matches the `recall_qa(host="all")` pattern from v2.0.0a6 / v3.0.0a4.

## Real numbers

- 1/1 v4.0.0a4-retro action item shipped
- 0 PRs opened — merged via `git merge --no-ff`
- 14 new unit tests (10 in test_auto_reembed.py + 4 UI route tests)
- Test suite delta: 650 + 2 skips → **664 + 2 skips**
- `mypy --strict` clean across **49 source files** (+1: auto_reembed.py)
- `ruff` clean across `src/` and `tests/`
- 0 backwards-incompatible changes — opt-in via config, default False

## What worked

- **Mirrored the v3.0.0a2 bridge-state pattern exactly.** Atomic
  write, missing-file → idle defaults, env-var override for tests.
  Two cross-process state files now follow the same recipe; future
  state surfaces should reuse the pattern.
- **Daemon thread, not asyncio task.** The MCP server's stdio path
  is sync; daemon thread plays nicely with both stdio + HTTP. Same
  reasoning v1.0.0a6 used for `HeartbeatLoop`.
- **Per-host runner isolation.** Each `_reembed_one_host` swallows
  its own exceptions; the loop accumulates errors and reports them
  in the final state. One bad host doesn't poison the rest.
- **Test stub stores.** `_StubStore` mimics `has_embedding_drift +
  reembed + close` without needing real sqlite + fastembed setup.
  Test suite stays fast and hermetic.

## What to change / next

- **No retry on transient failure.** A flaky open or a partial
  reembed marks the host as failed and moves on. Operator can re-run
  after fixing the underlying issue. Acceptable trade-off; an
  exponential-backoff retry path could land if observed.
- **No UI panel rendering /api/history/state.** The endpoint is in
  place; the dashboard panel that polls it is the next polish step.
  Defer; operators can `curl` the endpoint today.
- **Auto-reembed runs to completion before serving traffic.** No —
  daemon thread runs in parallel. recall_qa during reembed will
  return whatever the in-flight state shows. Acceptable for an
  opt-in operational flow.

## Action items for the next sprint (v4.0.0a6)

1. **Multi-worker dispatcher pool with thread-safety proof.** v3.0.0a5
   shipped a single-worker dispatcher because MCP tool state wasn't
   proven thread-safe. v4.0.0a6 starts with a stress test (50
   concurrent recall_qa / ask_project / project_status calls); if
   green, ship a bounded ThreadPoolExecutor sized by new
   [bridge] dispatcher_max_workers config. If the stress test
   surfaces an issue, ship the test as a regression guard and
   defer the pool change.

## Out-of-scope (still)

- Tauri / Electron desktop UI — no demand.
- Relay-binary path (Path B) — Path C HTTP tunnel covers it.
- IDE extension — MCP works with any MCP client.
- pnpm v5 lockfile support — pre-2022 format.
- Session-cookie auth + CSRF — defer until multi-operator UI is real.
- SSE end-to-end browser test — needs backend mocking; defer to a6.
- IE11 / pre-2018 clipboard fallback — modern-browser-only is fine.
- Double-tap-to-reset / keyboard shortcuts on graph zoom — defer.
- Reconciliation cross-fade / writeback spinner — defer until noticed.
- Auto-reembed exponential-backoff retry — defer until observed.
- Auto-reembed UI panel — endpoint exists; panel is next polish.

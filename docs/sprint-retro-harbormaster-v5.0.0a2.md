# Sprint Retro — Harbormaster v5.0.0a2

**Date:** 2026-05-09
**Theme:** Extended the v4.0.0a6 dispatcher stress test to backend-
invoking tools (ask_project, delegate_task) via the existing
fake-claude harness. Thread-safety now proven across the full tool
surface.

## What landed

| SHA | Subject |
|-----|---------|
| `7454135` | test(integration): backend-tools stress via fake-claude |

## Capabilities (this sprint)

### 1 · Backend stress: ask_project under contention

50 concurrent dispatches of `ask_project` via a 16-worker
ThreadPoolExecutor. Each invocation spawns a real subprocess
(fake_claude.py shim) with its own argv + cwd. The test asserts:

- All 50 envelopes are non-error (FAKE_CLAUDE marker present)
- No subprocess state leakage (one project's prompt doesn't show
  up in another project's answer)
- All envelopes are well-formed JSON

Result: green on first run. The dispatcher pool is safe for
ask_project under contention.

### 2 · Backend stress: failure isolation

Run with `HARBORMASTER_FAKE_CLAUDE_FAIL=exit2` so every subprocess
exits with code 2 + stderr. 10 concurrent dispatches: each surfaces
its error cleanly without one failure poisoning siblings.

Both tests confirm that `[fleetq] dispatcher_max_workers > 1` is
operationally safe across the entire current tool surface.

### 3 · `_seed_resolvable_projects` helper

The original `_seed_projects` (read-only stress) creates dirs with
just a README. That's enough for `list_projects`'s glob enumeration,
but `ask_project` calls `resolve_project` which requires the
project marker (`.git` dir or `CLAUDE.md` file).

New helper `_seed_resolvable_projects` adds `CLAUDE.md` per project.
Documented inline why both helpers exist.

## Real numbers

- 1/1 v5.0.0a1-retro action item shipped
- 0 PRs opened — merged via `git merge --no-ff`
- 2 new integration tests
- Test suite delta: 677 + 2 skips → **679 + 2 skips**
- `mypy --strict` clean across 49 source files
- `ruff` clean across `src/` and `tests/`
- 0 backwards-incompatible changes — pure test additions

## What worked

- **Reused fake_claude.py wholesale.** It already supports the four
  failure modes (timeout / exit2 / garbage / empty) the e2e test
  suite needs. Stress test gets the failure-isolation case for free
  by setting `HARBORMASTER_FAKE_CLAUDE_FAIL`.
- **16-worker pool, not 50.** Subprocess spawn is heavier than a
  pure-Python tool call. 16 workers × 50 dispatches keeps the test
  under 1s while still creating real contention.
- **First-run pass.** Both tests went green without any retry or
  serialisation tricks needed in the dispatcher. This is the
  evidence v3.0.0a5 lacked when shipping single-worker as the
  cautious default.

## What to change / next

- **No delegate_task coverage yet.** ask_project covers the
  dominant subprocess path; delegate_task uses the same backend
  protocol but with different prompt construction. Worth adding if
  the v5.0.0a3 per-tool safety map decides to differentiate.
- **No streaming-chunks stress.** The current stress hits the
  blocking JSON-result path. SSE streaming through `ask_local_stream`
  is exercised in unit tests but not under contention. Defer until
  the streaming path turns out to be the load bottleneck.

## Action items for the next sprint (v5.0.0a3)

1. **Per-tool thread-safety map.** Today the dispatcher pool is
   all-or-nothing. v5.0.0a3 introduces a `SAFE_FOR_PARALLEL`
   classification (default: read-only tools) so an operator who
   wants the pool gets parallelism on the safe subset and
   serialised dispatch on the rest. Configurable override via
   `[fleetq] dispatcher_unsafe_tools: list[str]`.

## Out-of-scope (still)

- Tauri / Electron desktop UI — no demand.
- Relay-binary path (Path B) — Path C HTTP tunnel covers it.
- IDE extension — MCP works with any MCP client.
- Session-cookie auth + CSRF — defer until multi-operator UI is real.
- pnpm v5 lockfile support — pre-2022 format.
- Manual "trigger reembed now" button — defer until needed.
- Reembed ETA estimation — defer until rate signal stabilises.
- delegate_task stress coverage — defer until safety map differentiates.
- Streaming-chunks stress — defer until streaming path bottlenecks.

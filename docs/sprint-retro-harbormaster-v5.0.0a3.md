# Sprint Retro — Harbormaster v5.0.0a3

**Date:** 2026-05-09
**Theme:** v4.0.0a6 dispatcher pool was all-or-nothing. v5.0.0a3 makes
it selective: known-safe tools fan out, unknown / deny-listed tools
serialise on the worker.

## What landed

| SHA | Subject |
|-----|---------|
| `ab3c319` | feat(fleetq): per-tool thread-safety map |

## Capabilities (this sprint)

### 1 · `SAFE_FOR_PARALLEL` allowlist

```python
SAFE_FOR_PARALLEL: frozenset[str] = frozenset({
    "list_projects", "list_hosts", "project_status",
    "project_graph", "recall_qa",
    "ask_project", "delegate_task", "fan_out_ask",
})
```

Every v3-shipped tool is in the set — they were all proven safe
under contention by the v4.0.0a6 stress (read-only) and v5.0.0a2
stress (backend-invoking).

Future tools must be added to this set explicitly. Third-party plugin
tools default to **unsafe** until the operator either adds them to
the allowlist or proves them safe via stress testing.

### 2 · `is_tool_safe_for_parallel(payload, unsafe_tools)`

Pure helper that decides routing per dispatch:

- `tools/list` → always safe (introspection only)
- `tools/call` with name in `SAFE_FOR_PARALLEL` and not in the
  operator deny list → safe
- Unknown tool name OR malformed payload OR deny-listed → unsafe
  (route to single-worker)

### 3 · `[fleetq] dispatcher_unsafe_tools` deny list

```toml
[fleetq]
dispatcher_max_workers = 4
dispatcher_unsafe_tools = ["my_plugin_tool", "ask_project"]
```

Operator-managed deny list always wins over the allowlist. Use cases:

- Third-party plugin not yet stress-tested → safest default to leave it on the worker
- A first-party tool turning out to share state in production → flip
  it to unsafe without redeploying

### 4 · Hot-path routing in `_worker_loop`

```python
if self._dispatcher_pool is not None:
    if is_tool_safe_for_parallel(payload, unsafe_tools=self._dispatcher_unsafe_tools):
        self._dispatcher_pool.submit(...)  # parallel
        continue
    # else fall through → inline single-worker dispatch
```

Single check per dispatch; the deny set is `frozenset` for O(1)
membership. No new threading primitives introduced.

## Real numbers

- 1/1 v5.0.0a2-retro action item shipped
- 0 PRs opened — merged via `git merge --no-ff`
- 9 new unit tests (5 dispatcher + 4 relay-routing)
- Test suite delta: 679 + 2 skips → **688 + 2 skips**
- `mypy --strict` clean across 49 source files
- `ruff` clean across `src/` and `tests/`
- 0 backwards-incompatible changes — the pool default flag stays
  `dispatcher_max_workers=1`; safety gate only kicks in when pool > 1

## What worked

- **Pure helper, not a method.** `is_tool_safe_for_parallel` lives on
  the dispatcher module and takes the payload + frozenset as args.
  Two callers (the relay's worker loop today, possibly a future
  HTTP-direct route) share the same logic without any state.
- **Default-deny for unknown tools.** A third-party plugin that lands
  in `[plugins] allow` doesn't automatically join the pool. The
  operator decides — by adding the tool to `SAFE_FOR_PARALLEL` (PR)
  or testing it themselves before promoting.
- **Mixed-workload test.** The hardest assertion to make is "safe
  fan out, unsafe serialise" simultaneously. Test counts distinct
  thread IDs per tool kind; verifies that unsafe tools only hit one
  thread (the worker) while safe tools see multiple.
- **`tools/list` is always safe.** Operators don't need to think
  about the introspection method; it's a pure read of the registry.

## What to change / next

- **No CLI introspection of the safety set.** `harbormaster-mcp
  plugins list` shows allowed plugins; a similar `dispatcher
  status` could surface SAFE_FOR_PARALLEL + unsafe deny list at
  startup. Defer.
- **Static frozenset, not config-driven.** Adding a tool to the
  allowlist requires a code change. That's intentional — the
  allowlist is a safety claim, not a config knob. Operators with
  a tool they want to promote can test it with `dispatcher_max_workers=1`
  first, then ship a PR.

## Action items for the next sprint (v5.0.0a4)

1. **Optimistic trajectory polish.** v4.0.0a4 introduced optimistic
   entries with a cyan border, but the optimistic→real transition
   is abrupt. Add Alpine `x-transition` cross-fade (200ms) and a
   subtle "writing back…" spinner on optimistic entries older than
   5 seconds.

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
- Config-driven safety allowlist — keep code-controlled by design.
- CLI dispatcher-status command — defer.

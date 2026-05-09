# Sprint Retro — Harbormaster v3.0.0a2

**Date:** 2026-05-09
**Theme:** Live FleetQ runtime state surfaced to the UI via cross-process
state file — operators can now see "is the bridge actually connected"
at a glance, not just "is it configured."

## What landed

### `harbormaster` (this repo)

| SHA | Subject |
|-----|---------|
| `f6b8b9e` | feat(fleetq): live bridge runtime state in /api/bridge/status (v3.0.0a2) |

## Capabilities (this sprint)

### 1 · `/api/bridge/status` reports live connection state

Before: `/api/bridge/status` was 100% config-derived. It told you whether
the bridge was *configured* (env var set, base_url valid) but not whether
it was *connected*. Operators had to tail the MCP process logs to know.

After: a new `runtime` block reports the actual current state, refreshed
every heartbeat interval. Three flavours of "not green":

- `connected: false` → bridge never registered or stop() ran
- `connected: true, stale: true` → writer hasn't ticked in >30s (writer
  process likely dead — failed silently)
- `connected: true, subscribed: false` → registered but Reverb subscribe
  hasn't completed yet (transient, <1-2s in practice)

Wire shape (cross-process state file `~/.harbormaster/bridge-state.json`):

```json
{
  "connected": true,
  "subscribed": true,
  "team_id": "...",
  "session_id": "...",
  "last_heartbeat": 1715260000.0,
  "last_error": null,
  "writer_pid": 12345
}
```

UI response shape (`/api/bridge/status` adds a `runtime` block):

```json
{
  "fleetq_enabled": true,
  ...,
  "runtime": {
    "available": true,
    "state_file_present": true,
    "stale": false,
    "age_seconds": 4.2,
    "connected": true,
    "subscribed": true,
    "team_id": "...",
    "session_id": "...",
    "last_heartbeat": 1715260000.0,
    "last_error": null,
    "writer_pid": 12345
  }
}
```

### 2 · Dashboard badge follows runtime state

The bridge status badge now flips:

- **emerald** — connected, subscribed, fresh (<30s)
- **cyan** — connected, not yet subscribed (transient)
- **amber** — stale (writer >30s silent) or token missing
- **rose** — disconnected with last_error
- **gray** — disabled

Tooltip surfaces last_heartbeat age and writer PID for diagnosis.

## Real numbers

- 1/1 v3.0.0a1-retro action item shipped (live runtime state)
- 0 PRs opened — merged `feat/v3.0-live-bridge-status` directly via `--no-ff`
- 14 new unit tests in `tests/unit/test_bridge_state.py`
- Test suite delta: 566 + 1 skip → **580 + 1 skip**
- `mypy --strict` clean across 48 source files
- `ruff` clean across `src/` and `tests/`
- 0 backwards-incompatible changes — `runtime` block is additive,
  `state_writer` defaults to `None` on HeartbeatLoop / BridgeRelay

## What worked

- **Tempfile-then-rename atomicity.** Standard pattern, but it's the
  difference between "UI sometimes shows half-written JSON" and "UI
  always shows a coherent snapshot." The reader uses
  `Path.read_text()` which is a single read syscall; combined with
  `os.replace()` on the writer side, there is no observable race.
- **Two-axis staleness check.** `connected: true` from the state file
  alone isn't enough — the writer process could be dead. Pairing it
  with `freshness_seconds=30` gives the UI three states (green / amber
  stale / red disconnected) for operator-meaningful colour coding.
- **Writer never raises.** `BridgeStateWriter._write()` swallows every
  exception (logged at warning). The heartbeat thread can't be killed
  by a full disk or a chmod'd parent dir. Tested explicitly via the
  read-only tempdir test case.

## What to change / next

- **No file-locking.** The writer is a single process so cross-process
  contention on the state file is theoretical. If we ever run two MCP
  processes concurrently (e.g. dev + production on the same host) they
  will overwrite each other's state. Acceptable for v3 — flag for v4
  if multi-process becomes real.
- **Dashboard tooltip is browser-default styling.** Custom Alpine
  tooltip would look better, but it's a polish pass on top of polish.
  Defer.

## Action items for the next sprint (v3.0.0a3)

1. **pnpm-lock + yarn.lock parsers.** Extends v2.0.0a1 lockfile parsing.
   Both formats deferred at v2 ship time because pnpm-lock requires
   YAML and yarn split between v1 (custom) and Berry (YAML). Pure
   parsers in `harbormaster.graph.lockfile`. No protocol changes.

## Out-of-scope (still)

- Tauri / Electron desktop UI — no demand.
- Relay-binary path (Path B) — Path C HTTP tunnel covers it.
- IDE extension (VS Code / JetBrains) — MCP works with any MCP client.
- Cross-process file locking — only one MCP writer in practice.

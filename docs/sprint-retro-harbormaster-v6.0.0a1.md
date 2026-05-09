# Sprint Retro — Harbormaster v6.0.0a1

**Date:** 2026-05-09
**Theme:** Closed the v5.0.0a1 retro gap on auto-reembed visibility:
operators can now trigger a run on demand, and the panel surfaces
an ETA once rate signal stabilises.

## What landed

| SHA | Subject |
|-----|---------|
| `6f3392f` | feat(history+ui): manual reembed trigger + ETA estimation |

## Capabilities

### 1 · `POST /api/history/reembed` endpoint

```
POST /api/history/reembed         → 200 {"started": true}
                                  → 409 (already in progress)
                                  → 400 ([history] disabled)
                                  → 503 ([history] extra not installed)
```

`trigger_manual_reembed(config)` spawns the same background runner as
the startup-time auto-reembed. Idempotent under double-click + multi-tab
race: refuses to start a second run while one is in progress. Does NOT
honour `auto_reembed_on_drift` — the operator action is the gate.

### 2 · "Run now" button in the dashboard panel

`reembedPanel` gained a button beside the phase badge. Disabled while
running. Clicking triggers the POST endpoint, then immediately polls
the state file to flip the panel into running mode.

### 3 · ETA estimation in `progressLabel()`

```
processing host: friday        2 / 5 · ~12s remaining
```

Computed from rate signal: `(now - started_at) / processed × (total - processed)`.
Activates once `processed >= 1` (need at least one completed host
to extrapolate). Format: `Xs` / `X.Xm` / `X.Xh` auto-scaling.

## Real numbers

- 1/1 v5.0.0-retro action item shipped (manual trigger button +
  ETA, both bundled — same subsystem)
- 0 PRs opened — merged via `git merge --no-ff`
- 8 new tests (3 unit + 5 UI)
- Test suite delta: 702 + 2 skips → **710 + 2 skips**
- `mypy --strict` clean across 49 source files
- `ruff` clean across `src/` and `tests/`
- 0 backwards-incompatible changes — additive endpoint + UI

## What worked

- **Idempotency at the runner level.** `trigger_manual_reembed`
  reads the state file BEFORE spawning the thread; the cross-process
  state file is the source of truth. A second tab firing the same
  POST gets a 409 without race conditions.
- **HTTP status codes match semantics.** 409 for "conflicting state",
  400 for "your config disabled this", 503 for "missing extra". Each
  has a different operator action (wait / configure / install).
- **ETA via rate signal, not estimate.** No "expected duration per
  host" heuristic — just measured rate. Wrong on host 1; converges
  fast as more hosts complete. Acceptable tradeoff: one inaccurate
  reading vs. a wrong-by-design hardcoded estimate.
- **Reuse of v4.0.0a5 plumbing.** The runner, state file, and reader
  all stayed unchanged. v6.0.0a1 is a thin wrapper on top.

## What to change / next

- **No "cancel running reembed" button.** Once started, the run
  goes to completion. Acceptable today (per-host runs are bounded
  in time). Defer until observed.
- **No history of past runs.** state.json is overwritten each run;
  operators don't see "ran 3 times today, last took 4m". Defer.

## Action items for the next sprint (v6.0.0a2)

1. **Optimistic escalation tier + configurable threshold.** The
   v4.0.0a4 + v5.0.0a4 single-tier (5s amber spinner) flattens to
   "kind of stale = very stale". Add a third tier (>30s → red
   "writeback stuck?") and make the threshold configurable via
   `[history] optimistic_stale_seconds`.

## Out-of-scope (still)

- Tauri / Electron desktop UI — no demand.
- Relay-binary path (Path B) — Path C HTTP tunnel covers it.
- IDE extension — MCP works with any MCP client.
- Session-cookie auth + CSRF — defer until multi-operator UI is real.
- pnpm v5 lockfile support — pre-2022 format.
- Cancel-running-reembed button — defer until observed.
- Reembed run history — defer until needed.

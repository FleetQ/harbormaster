# Sprint Retro — Harbormaster v7.0.0a3

**Date:** 2026-05-09
**Theme:** Operator control. Top of the v6 retro candidate list — let
operators stop a long-running reembed without restarting the process.

## What landed

### `harbormaster` (this repo)

| SHA | Subject |
|-----|---------|
| `7880bce` | feat(history): cancel-running-reembed button + cooperative cancel flag |

## Capabilities (this sprint)

### 1 · Cooperative cancel for in-flight reembed runs

Wire shape:

```
POST /api/history/reembed/cancel
→ 200 {"running": bool, "cancel_requested": bool, "phase": str}
→ 503 when [history] extra not installed
```

Idempotent: cancelling a non-running reembed returns
`{"running": false, "cancel_requested": false}`. Cancelling a
running reembed sets `cancel_requested: true` in the cross-process
state file (`~/.harbormaster/reembed-state.json`).

The worker (`run_auto_reembed`) re-reads the state file at the
top of each host iteration. When it sees the flag set, it stops
the loop and writes `phase = "cancelled"`, `current_host = null`,
`finished_at = <now>`, `cancel_requested = false` (cleared so the
next run starts clean).

The cancel flag is **never** honoured mid-host — a single host's
reembed is treated as the smallest atomic unit so we don't leave
half-processed sqlite-vec rows behind.

### 2 · UI cancel button + cancelling state

The reembed panel on the dashboard now renders an amber cancel
button while `state.phase === 'running' && !state.cancel_requested`.
After click, `phaseLabel()` shows "cancelling…" and the badge
turns amber until the worker acknowledges by writing
`phase = "cancelled"`. A `Cancelled after N of M hosts` message
replaces the progress block on the terminal-cancelled state.

### 3 · State race fix

Pre-existing cancel flag is now preserved through runner startup
(read state at entry, copy `cancel_requested` into the new
`ReembedState`). Without this, a cancel set in the tiny window
between `trigger_manual_reembed()` returning and the worker
thread's first instruction would be silently overwritten.

## Real numbers

- 1/1 v7.0.0a3 phase action items shipped
- 1 feature branch merged (no PR)
- 8 new unit tests + 1 new template assertion (743 → 754 collected;
  730 → 738 actually run under default profile, +1 skipped)
- mypy --strict + ruff: clean (50 source files unchanged)
- Backwards-incompatible changes: 0 (new field defaults to False;
  new endpoint is additive; existing GET /api/history/state grew
  one new field)

## What worked

- **Test the runner without spinning up the thread.** The cancel-
  observation test calls `run_auto_reembed` directly with a
  pre-set state file. No threads, no flakiness, deterministic.
  The threading is covered by the existing v4.0.0a5 tests; we
  don't need to re-prove it here.
- **One-flag-fits-all cancel surface.** Same `cancel_requested`
  field is read by the worker, surfaced in the API state, and
  consumed by the UI badge. No secondary "cancel pending" state
  in the UI store — the UI just renders what the API returns.

## What to change / next

- **Pre-existing cancel flag preservation is implicit.** The runner
  reads pre-state at entry, but a future refactor could miss why
  that read is there. Worth a comment-block explanation in the
  v7.0.0a3 retro context — done in the source comment, but a
  matching unit test for "cancel set BEFORE thread start is honoured"
  would lock the invariant. Already covered in
  `test_runner_observes_cancel_flag_and_stops`; consider it locked.

## Action items for the next sprint (v7.0.0a4)

1. **Reembed run history (state.json log).** Append every reembed
   run record to `~/.harbormaster/reembed_history.json` (cap at
   last 50). Serve via `GET /api/history/reembed/runs`. Render a
   collapsible "last 5 runs" table on the reembed panel.

## Out-of-scope (still)

- Mid-host cancel — would require rewriting the QAStore.reembed()
  loop to accept a callback. Not worth it; a single host completes
  in <1s for typical store sizes.
- Cancel a scheduled (not-yet-started) reembed — there isn't a
  scheduling layer, the `auto_reembed_on_drift` thread just runs
  on startup. Add a real scheduler before adding cancel-future.

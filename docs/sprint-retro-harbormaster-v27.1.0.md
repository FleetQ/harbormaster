# Sprint Retro — Harbormaster v27.1.0

**Date:** 2026-07-06
**Theme:** stdio no longer runs the FleetQ bridge/auto-reembed (per-connection
stdio processes were spawning duplicate bridges, spamming 401 heartbeat
retries — 14.7k lines/5.5MB in one Desktop log — and leaking orphaned daemon
threads → "Server disconnected"). Fix gates background subsystems behind
`args.transport != "stdio"` + new opt-in `[fleetq] bridge_in_stdio`. Bundles
`d8accf3` resilient orphan recovery. A stability + reliability patch release,
not a feature sprint.

## What landed

### `harbormaster` (this repo)

| SHA | Subject |
|-----|---------|
| `f6bd37c` | fix: don't run FleetQ bridge + auto-reembed on the stdio transport (#33) |
| `d8accf3` | feat: resilient orphan recovery for delegated jobs |

## Capabilities (this sprint)

### 1 · stdio transport no longer starts the FleetQ Bridge or auto-reembed worker

Claude Code / Desktop spawn a fresh stdio `harbormaster-mcp` process per
connection. `main()` previously started the FleetQ Bridge (heartbeat loop +
relay websocket) and the auto-reembed worker *before* checking the transport,
so every ephemeral stdio process registered a duplicate bridge with FleetQ,
ran a 30s heartbeat-retry loop that spammed 401s into the client's stderr,
and left orphaned daemon threads alive after the client closed the pipe —
surfacing to the user as "Server disconnected" while stale processes lingered
for hours.

Both subsystems are singleton, long-lived processes that belong to the
persistent HTTP server (launchd-managed), not to per-connection stdio tool
surfaces. They are now gated behind `args.transport != "stdio"`, with a new
opt-in config knob for the rare single long-lived stdio host that should
itself act as the bridge:

```toml
[fleetq]
bridge_in_stdio = false  # default; set true to opt a long-lived stdio host back in
```

### 2 · Resilient orphan recovery for delegated jobs

Crash/restart no longer discards every in-flight delegated job. On boot,
`recover_orphaned()` now re-queues read-only jobs (safe to re-run) instead of
failing them, so the operator does not have to re-delegate. Write jobs are
still failed — a dead subprocess may have applied partial edits, so
auto-rerun risks double-applying, and a human should decide. A new
`recovery_count` column (idempotent migration) backs a poison-pill guard
(`MAX_RECOVERY_ATTEMPTS=1`) that stops a job which reliably crashes the
worker from re-queuing forever.

## Real numbers

- 2/2 items shipped (both were open work at the start of this release cut;
  no prior-sprint action-item list to reconcile against)
- 1 PR opened / merged (#33); 1 direct commit to `main` (`d8accf3`, no PR)
- New tests: `tests/unit/test_main_background_subsystems.py` (stdio skips both
  subsystems; opt-in `bridge_in_stdio` starts the bridge; HTTP transport
  starts both) + 4 new cases in `tests/unit/test_jobs_store.py` (requeue,
  write-fail, cap, mixed summary)
- Test suite delta: 2183 → 2187 passed, 1 skip (both held green in CI matrix:
  macOS/Ubuntu × py3.11/3.12/3.13)
- Lint / type-check: `ruff check src/ tests/` clean, `mypy --strict
  src/harbormaster/` clean (80 source files)
- Backwards-incompatible changes: 0 — `bridge_in_stdio` defaults to the new
  (fixed) behavior; opt-in knob preserves the old behavior for anyone who
  relied on it

## What worked

- **Gate at the call site, not deep in the subsystem.** The fix is a single
  conditional at the `main()` call site (`args.transport != "stdio"`) rather
  than threading transport-awareness into the Bridge/auto-reembed classes
  themselves — smallest possible diff for a subsystem-lifecycle bug, easy to
  reason about and easy to review.
- **Field log evidence over speculation.** The 14.7k-line/5.5MB Desktop log
  observation made the bug concrete and gave the fix a hard falsifiable
  target (does the log stop growing) instead of "seems flaky."
- **Bundling a ready, tested commit into the release cut.** `d8accf3` had
  already landed on `main` with its own tests before this release was cut;
  no extra validation work was needed to bundle it — it just rides along.

## What to change / next

- **No pre-flight smoke test caught the duplicate-bridge-on-stdio bug before
  it reached the field.** The CI smoke suite covers HTTP transport bridge
  behavior but had no stdio-transport assertion that background subsystems
  stay off. `test_main_background_subsystems.py` closes this gap going
  forward, but it shipped reactively, after a field report, not proactively.
- **`d8accf3` and `f6bd37c` were developed independently and only combined at
  release-cut time.** That's fine for two unrelated fixes, but there was no
  explicit check that resilient-orphan-recovery's boot-time `recover_orphaned()`
  path and the new stdio transport gate don't interact (they don't — orphan
  recovery runs regardless of transport — but that was verified after the
  fact, not designed in from the start).

## Action items for the next sprint (v27.2.0 / week 1)

1. **Add a live stdio-transport smoke test to CI.** Mirror the existing
   `Live FleetQ Bridge smoke (gated)` job but assert the *absence* of bridge
   registration/heartbeat traffic when `--transport stdio` is used, so a
   future regression fails CI instead of surfacing as a field log report.
2. **Document `bridge_in_stdio` in the operator config reference with a
   worked example.** The knob exists and is tested, but the single long-lived
   stdio host use case (who would actually set this true) isn't spelled out
   for operators deciding whether they need it.
3. **Audit other background subsystems for the same per-connection-stdio
   assumption.** The bridge and auto-reembed worker both had this bug; check
   whether any other `main()`-started subsystem makes the same "one process,
   one instance" assumption that stdio's per-connection spawn model breaks.

## Out-of-scope (still)

- Plugin-registered third-party orchestrator adapters (seam present since
  v27.0.0, not shipped) — no external consumer request yet.
- Antigravity CLI (Gemini CLI successor) adapter verification — mapped via
  substring to the `gemini` adapter as a placeholder; needs empirical
  confirmation the subagent contract carries over.
- Empirical `clientInfo.name` mapping table per CLI — deferred until more
  non-Claude clients are observed in the field.

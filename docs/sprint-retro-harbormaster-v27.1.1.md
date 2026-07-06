# Sprint Retro — Harbormaster v27.1.1

**Date:** 2026-07-06
**Theme:** capped exponential backoff on the FleetQ bridge register-retry
loop (a dead/expired token previously made `register()` retry every 30s
forever — 14.7k lines / 5.5MB in one Claude Desktop log). Now doubles from
`interval` to a 15-minute ceiling and resets on first success;
registered-state heartbeats still tick at `interval`. Defense-in-depth
companion to v27.1.0 (stdio no longer runs the bridge) — this closes the
same failure class for the HTTP-transport bridge that *does* run.

## What landed

### `harbormaster` (this repo)

| SHA | Subject |
|-----|---------|
| `985c20a` | fix: exponential backoff on FleetQ bridge register-retry loop (#34) |

## Capabilities (this sprint)

### 1 · Capped exponential backoff on `HeartbeatLoop` register-retry

`HeartbeatLoop` previously retried a failed `register()` every `interval`
(30s) forever. An expired or revoked token turns every attempt into a 401 —
not a transient failure — so a dead token produced a 30s retry storm that
flooded stderr (a field-observed 14k+ lines / 5.5MB in a single Claude
Desktop log, the same failure signature that motivated v27.1.0's stdio gate).

The retry delay now doubles from `interval` per consecutive register
failure, capped at 900s (15 minutes), and resets to 0 on the first
successful register. Registered-state heartbeats are unaffected — they
still tick at `interval`. The warning log line now reports the attempt
count and the computed next-retry delay, e.g.:

```
FleetQ bridge register failed (attempt 4): <error> — next retry in 240s
```

The exponent is clamped (`min(failures - 1, 16)`) before the `1 << exp`
shift so it can't overflow before the cap applies — `2 ** <non-literal>`
would otherwise widen to `Any` under `mypy --strict`.

## Real numbers

- 1/1 items shipped (single-issue patch release, no prior-sprint action-item
  list to reconcile against)
- 1 PR opened / merged (#34, squash-merged)
- New tests: 3 in `tests/unit/test_heartbeat.py` (exponential growth, cap +
  no-overflow, reset-on-success)
- Test suite: 2190 passed, 1 skip (full suite, CI matrix macOS/Ubuntu ×
  py3.11/3.12/3.13 all green)
- Lint / type-check: `ruff` clean, `mypy --strict` clean
- Backwards-incompatible changes: 0 — behavior only changes for the
  previously-broken case (persistent register failure); transient-failure
  recovery timing is unchanged for the first retry

## What worked

- **Field log evidence over speculation.** As with v27.1.0, a concrete log
  artifact (14.7k lines / 5.5MB from a real dead-token session) gave the fix
  a falsifiable target — "retry count drops ~30x under a persistent auth
  failure" — instead of a vague "this seems noisy" report.
- **Small, isolated diff.** The fix is contained to `HeartbeatLoop`'s
  register-retry path (one new method, one loop-condition change) with no
  changes to the registered-state heartbeat cadence — low blast radius for
  a patch release.

## What to change / next

- **The 401-storm failure class had two separate fixes shipped one sprint
  apart** (v27.1.0 gated the bridge off stdio entirely; v27.1.1 caps the
  retry loop for the transports where the bridge legitimately runs). Both
  originated from the same field log. Worth checking whether a single
  earlier investigation could have caught both at once, or whether the
  two-sprint split was actually the right call (stdio gate was the bigger,
  riskier change and shipped first on its own).

## Action items for the next sprint (v27.2.0 / week 1)

1. **Add a live smoke test asserting backoff behavior under a forced 401.**
   Existing smoke jobs cover the happy-path bridge register; none exercise
   a persistent-auth-failure scenario end-to-end the way the new unit tests
   do at the unit level.
2. **Carry over from v27.1.0: add a live stdio-transport smoke test to CI**
   asserting the *absence* of bridge registration/heartbeat traffic when
   `--transport stdio` is used.
3. **Carry over from v27.1.0: document `bridge_in_stdio` in the operator
   config reference** with a worked example for the single long-lived stdio
   host use case.

## Out-of-scope (still)

- Plugin-registered third-party orchestrator adapters (seam present since
  v27.0.0, not shipped) — no external consumer request yet.
- Antigravity CLI (Gemini CLI successor) adapter verification — mapped via
  substring to the `gemini` adapter as a placeholder; needs empirical
  confirmation the subagent contract carries over.
- Empirical `clientInfo.name` mapping table per CLI — deferred until more
  non-Claude clients are observed in the field.

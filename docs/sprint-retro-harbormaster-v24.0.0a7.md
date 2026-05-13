# Sprint Retro — Harbormaster v24.0.0a7

**Date:** 2026-05-13
**Theme:** Close out Tier 3 from "make all remaining". The
fleetq-bridge sub-agent shipped `POST /api/v1/harbormaster/job-completed`
in an async-delegated session earlier today; this alpha wires
harbormaster's JobStore to publish completions to that endpoint.

## What landed

| File | Subject |
|---|---|
| `src/harbormaster/fleetq/completions.py` | new — `CompletionPublisher` class + `_build_payload`; off-thread POST so JobStore worker is never blocked |
| `src/harbormaster/config.py` | `FleetQConfig.publish_completions: bool = False` + `team_id: str = ""` |
| `src/harbormaster/jobs/subsystem.py` | wires publisher as JobStore subscriber when armed; three-gate check matches v16 FleetQ writeback pattern |
| `docs/operator-config-reference.md` | `[fleetq]` table extended with the two new keys |
| `tests/unit/test_fleetq_completions.py` | 12 new tests (3 disarm gates, terminal-only firing, payload shape + trimming, error swallowing, subsystem wiring on/off) |
| `src/harbormaster/__init__.py` | 24.0.0a6 → 24.0.0a7 |

## Numbers

- 6 files (2 new, 4 modified). ~270 LOC net.
- 2037 → 2049 tests (+12). mypy --strict clean on 76 source files.
  ruff clean.

## Capability

### Three-gate arm check (matches v16 FleetQ writeback pattern)

The publisher fires ONLY when all three of these are satisfied:
1. `[fleetq] publish_completions = true`
2. `[fleetq] team_id = "<uuid>"` non-empty
3. `os.environ[<api_token_env>]` resolves to a non-empty value

Bare-default operators see no behaviour change. Existing FleetQ
operators who don't opt in stay on the current SSE-only push.

### Off-thread POST

Every `publish(job)` call spawns a daemon `threading.Thread` for the
POST. This keeps the JobStore worker's hot path under 100 µs (just
build-payload + spawn-thread) even when the relay is slow or
unreachable. Network errors are logged + swallowed — the JobStore
row and the SSE channel both still capture the event for replay.

### Wire payload matches fleetq-bridge contract verbatim

Per the FleetQ sub-agent's delivery report:
- `job_id`, `team_id`, `project`, `host`, `task` (≤ 2000 chars),
  `deliverable` (≤ 1000), `allow_writes`, `status`, `output` (≤ 4000),
  `error` (≤ 4000), `cid`, `queued_at`, `completed_at`, `duration_ms`,
  `model`, `max_turns`, `inbox_id`
- Bridge trims output/error to 1000 chars on the Pusher wire; we ship
  full 4000-char payloads to the bridge and let it shape downstream.

## Lessons

### Cross-project delegation works end-to-end

The harbormaster MCP delegate_task(mode="async") fired against
fleetq-bridge from this session at 09:11 UTC. Sub-agent worked for
~7.5 minutes (449.5s), produced a 3.3 KB markdown report with
files-changed list + commit SHAs + curl smoke test + Pusher channel
contract — exactly the deliverable shape the prompt asked for. v24
shipping this subscriber closes the loop: harbormaster ↔ FleetQ
bidirectional push.

This is the **first** real production cross-project async delegation
in the v22 surface. The collector3.0 attempt failed at
max_turns_reached (v22.0.1 incident); this one succeeded with
max_turns=80. Empirical guideline validated.

### `os.environ` snapshot at construction is acceptable

`CompletionPublisher.__init__` reads `os.environ[api_token_env]`
ONCE at boot. Token rotation requires daemon restart (already
required for any v22+ JobStore migration anyway). Documented in the
class docstring; pattern matches every other env-token-using
subsystem in harbormaster.

## Carry-over

- v24.0.0 GA: drop alpha, comprehensive v24 arc retro, memory refresh

## Operator-facing note

To enable the FleetQ Bridge completion publisher after v24.0.0a7
upgrade:

```toml
[fleetq]
enabled = true
publish_completions = true
team_id = "<your-team-uuid>"
api_token_env = "FLEETQ_API_TOKEN"
```

Restart daemons (`launchctl kickstart`). Logs will show:

```
delegate-job subsystem: fleetq completion publisher armed
  (team_id=<uuid>, endpoint=https://app.fleetq.net/api/v1/harbormaster/job-completed)
```

External agents subscribed to Pusher channel
`private-harbormaster.<team_id>` will receive `delegate-job-completed`
events for every completion / failure. Channel-auth via FleetQ
Laravel app's `/pusher/auth` (operator-side wiring, see
fleetq-bridge `docs/integrations.md` from the sub-agent's report).

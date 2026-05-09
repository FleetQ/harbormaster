# Sprint Retro — Harbormaster v1.0.0a10

**Date:** 2026-05-09
**Theme:** Polish + foundations. The streaming and config-drift items
flagged in earlier retros, plus the post-mortem polish from the
HTTP-direct routing PR. No new product surface; all six action items
from the v1.0.0a9 retro shipped.

## What landed

### `harbormaster` (this repo)

| SHA | Subject |
|-----|---------|
| `b68e522` | ci(fleetq): add gated live FleetQ Bridge smoke job (#1) |
| `64a1d37` | feat(fleetq): config-watch loop — push update_endpoints on manifest drift (#2) |
| `0a03364` | feat(ui): SSE streaming for /mcp/{server} (heartbeat + final result) (#3) |

### `agent-fleet` (community-edition base submodule)

| SHA | Subject |
|-----|---------|
| `cd4e4735` | feat: merge feat/mcp-call-http-direct into develop (#72, carried in from a9) |
| (squash) | fix(bridge): pass 4xx daemon errors through, drop generic 502 wrap (#73) |

## Capabilities (this sprint)

### 1 · PyPI publish v1.0.0a9

The previous five tag pushes all failed with `invalid-publisher` —
PyPI's Trusted Publisher had never been registered for the project.
Resolved by registering pending publishers on both test.pypi.org and
pypi.org, then re-triggering the publish workflow via
`workflow_dispatch`. TestPyPI dry-run first, prod second, both green.
`harbormaster-mcp 1.0.0a10` will be the second public release.

### 2 · Streaming `tools/call` (SSE)

`POST /mcp/{server}` now branches on `Accept: text/event-stream`:

```
event: heartbeat        ← every 5s while the tool is still running
data:  {"elapsed_ms": <int>}

event: result           ← final MCP envelope (identical to JSON mode)
data:  <envelope JSON>

event: error            ← pre-dispatch failures (404, 400, etc.)
data:  {"status": <int>, "detail": <str>}
```

Tool exceptions still arrive as the regular MCP `isError` envelope
inside a `result` event — same semantics as JSON mode, so callers
don't need a different code path for streaming-vs-JSON failures.

JSON mode is bit-identical to a9. Purely additive.

The SSE branch dispatches the existing sync `_dispatch_mcp` via
`asyncio.to_thread` so the event loop stays free to emit heartbeats.

### 3 · `update_endpoints` config-watch loop

`HeartbeatLoop` now accepts `endpoints_factory: Callable[[], dict]`.
On every heartbeat tick the factory rebuilds the manifest; if the
result differs from the last-pushed snapshot, `update_endpoints` is
called and the drift baseline advances.

Today's `build_manifest()` is static, so this is a no-op in practice —
but the rails are in place for v1.1+ when discovery starts adding
hosts/agents to the manifest. The factory is invoked every interval,
so the docstring spells out the contract: pure, cheap, side-effect-free.

Failure modes are conservative:
- factory raises → log, skip this tick (heartbeat keeps going)
- `update_endpoints` raises → leave baseline unchanged, retry next tick
- re-register (after session loss) → sync baseline so we don't push twice

### 4 · Live FleetQ Bridge CI smoke (gated)

New `smoke-fleetq` CI job runs the full `register → heartbeat →
update_endpoints → heartbeat → disconnect` round trip against a real
FleetQ. Skipped by default — gated on `vars.FLEETQ_SMOKE_ENABLED ==
'true'` plus secrets `FLEETQ_TEST_BASE_URL` + `FLEETQ_TEST_API_TOKEN`.
Forks have access to neither the variable nor the secrets, so the job
is structurally unable to run on public PRs.

The smoke script `tests/smoke_fleetq.py` is intentionally stand-alone
(not pytest) so contributors can run it locally without a special
pytest invocation.

### 5 · agent-fleet PR #72 merged

Already done out-of-band before the sprint started — `cd4e4735` had
landed on `develop` overnight. CI on the merged commit was failing on a
single Pint style issue (`fully_qualified_strict_types` on
`ConnectionException`) and Tests was therefore skipped. Folded the fix
into the error-mapping PR below so both got cleaned up together.

### 6 · Error mapping polish (4xx pass-through)

`BridgeController::mcpCallViaHttp` previously wrapped every non-2xx
daemon response as 502. From a FleetQ caller's perspective, a daemon's
404 "tool not found" was indistinguishable from a gateway error.

After:

| Daemon response | Before | After |
|---|---|---|
| 4xx JSON | 502 wrap | forward status + body verbatim |
| 4xx non-JSON | 502 wrap | forward status, wrap body in `{error: …}` |
| 5xx | 502 wrap | 502 wrap (unchanged — daemon is the failing dep) |
| connect/DNS/timeout | 502 | 502 (unchanged) |

This also unblocked the `Tests` CI job on the agent-fleet repo (which
had been silently skipped for the last 24 hours because of the Pint
miss).

## Real numbers

- 6/6 v1.0.0a9 retro action items shipped
- 4 PRs opened, all 4 merged (3 on FleetQ/harbormaster, 1 on
  escapeboy/agent-fleet-o)
- 11 new unit tests (5 heartbeat + 6 streaming) + 3 BridgeControllerTest
  cases (1 renamed, 2 new)
- Test suite: 217 → 223 passed on harbormaster
- Pint: 3311 files clean (was 3310 with 1 style miss going in)
- `mypy --strict`: clean across 26 files
- 0 backward-incompatible changes

## What worked

- **Tooling-first sprint.** Three of the six items were CI / publish /
  diagnostics work, not user-visible features. Pinning these down before
  the v1.1 push means the first regression in v1.1 will land in a
  green-baseline pipeline, not a broken-baseline one. Easier to debug.
- **Persona-PR-per-action-item.** Each retro item became its own PR
  with its own CI run. Five separate green CIs gave more confidence
  than one big PR. Squash-merged so `main` history stays clean.
- **Forward-compat shapes.** SSE wire shape includes a `chunk` event
  type that nothing emits today — but the day a tool grows a real
  AsyncIterator output, the consumer doesn't need to change. Same on
  the FleetQ side: pre-dispatch errors are in-band SSE events with the
  original status code, not a mid-flight transport switch.
- **Failed-pipeline triage.** The PyPI `invalid-publisher` failure
  looked scary (5 consecutive failures with no human noticing). The
  fix was 5 minutes of UI work in pypi.org — the diagnostic step took
  longer than the resolution. Worth a runbook entry for next time.
- **Reading the retro before writing the next one.** All six items
  shipped were verbatim from the a9 retro's "action items" section.
  Discipline pays.

## What to change / next

- **FleetQ-side SSE consumer.** The streaming work is single-sided:
  harbormaster emits SSE, but `BridgeController::mcpCallViaHttp` still
  sends `Accept: application/json`. End-to-end streaming through the
  FleetQ proxy needs Laravel `response()->stream()` plumbing plus
  PHP-FPM / nginx output-buffer config to actually flush incrementally.
  Carry into a11.
- **Real token streaming.** Today's SSE only emits heartbeats and a
  final result — no per-token `chunk` events yet. Wiring `claude -p`
  stdout to an AsyncIterator on the harbormaster side would unlock
  true progressive UI. Probably v1.1 work, not a11.
- **Manifest is still static.** `update_endpoints` config-watch is
  wired but has nothing to detect today. The first real test of the
  drift-detection path will come when discovery starts adding hosts
  to the manifest — likely with the v1.1 A2A Agent Card per project
  work.
- **`smoke-fleetq` runs only on opt-in repos.** The gate is conservative
  (no token leak risk on forks) but means we won't notice a contract
  drift between agent-fleet and harbormaster until someone manually
  enables the variable on `FleetQ/harbormaster`. Worth automating that
  on every release-candidate tag.
- **Live FleetQ contract verification before each release.** With
  PyPI publishing now functional, every tag push goes public. Worth
  running the gated smoke job manually against `harbormaster-mcp ==
  $next_version` before tagging, to catch wire-shape regressions.

## Action items for the next sprint (v1.0.0a11 / week 11)

1. **FleetQ-side SSE consumer.** `BridgeController::mcpCallViaHttp`
   accepts a `stream=true` flag, opens an SSE connection to the daemon,
   forwards events back to the FleetQ caller via Laravel
   `response()->stream()`. Update PHP-FPM / nginx to disable output
   buffering on this route.
2. **Live FleetQ smoke before every release.** Either flip
   `FLEETQ_SMOKE_ENABLED=true` on the canonical CI repo, or add a
   manual `release-candidate` workflow that runs it against a private
   FleetQ instance.
3. **First-token streaming for `ask_project`.** Pipe `claude -p` stdout
   into an AsyncIterator and emit `chunk` SSE events. Reuses the
   forward-compat hooks from a10.
4. **Bump to v1.1 scope.** With the polish backlog cleared, time to
   start the FleetQ Platform Tool seeder and A2A Agent Card per project
   work outlined in `docs/design-harbormaster.md` §3 v1.1.
5. **Sprint retro template.** Five sprints in, the retro structure has
   stabilized. Worth a small template in `docs/` so future sprints
   don't reinvent the section ordering.

## Out-of-scope (still)

- Q&A history / federated KG / auto project graph — v1.2 roadmap.
- Backends other than Claude — wait for first user request.
- Plugin / extensions API — v2.
- Tauri / Electron native UI wrapper — post-v1.2.
- Relay-binary path (Path B) — explicitly skipped in favour of Path C.
- Real token-by-token streaming — wired up to a11 (item 3 above).

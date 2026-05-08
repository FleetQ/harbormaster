# Sprint Retro — Harbormaster v1.0.0a6

**Date**: 2026-05-08
**Mode**: continuation of `/sprint-orchestrate full` ("продължи")
**Goal**: ship the v1.1 headline — FleetQ Bridge integration — plus the v1.0.0a5-retro nit about UI token roundtrip in CI
**Outcome**: ✅ Tagged `v1.0.0a6`. 3 commits. 168 tests pass + 1 intentional skip. **First v1.1-track milestone shipped.**

---

## What landed

Three commits on `feat/harbormaster-v1.0.0a6`:

| SHA | Subject |
|-----|---------|
| `b784dc7` | feat(fleetq): Bridge integration — register, heartbeat, disconnect |
| `d6f265c` | ci: smoke-ui-with-token job — token roundtrip on the UI port |
| (this commit) | ship: bump to 1.0.0a6 + sprint retro |

**Diff vs v1.0.0a5**: ~10 files changed, +1100 / −20.

---

## Capabilities (this sprint)

### 1 · FleetQ Bridge integration (the headline)

The first piece of v1.1. Harbormaster can now register itself as a Bridge daemon in any FleetQ instance, advertise its 6 MCP tools in the endpoints manifest, heartbeat to keep the connection live, and gracefully deregister on shutdown. From the FleetQ side it shows up as `harbormaster on <hostname>` in the Connections UI.

Contract discovery walked through `agent-fleet/base/app/Http/Controllers/Api/V1/BridgeController.php` and the matching `Domain/Bridge/Actions/*` + `Models/BridgeConnection.php`. Result: [`docs/fleetq-bridge-contract.md`](fleetq-bridge-contract.md) — a self-contained spec of the four endpoints we hit, the auth shape (Sanctum bearer with `team:<uuid>` ability), the status enum, and what's deliberately deferred (reverse WebSocket relay → v1.0.0a7+).

Implementation:

```
src/harbormaster/fleetq/
├── __init__.py        # public exports: BridgeClient, BridgeError, RegisterResponse, HeartbeatLoop
├── bridge.py          # sync httpx client — register/heartbeat/update_endpoints/disconnect/close
└── heartbeat.py       # daemon thread — start() registers + spins, stop() disconnects + closes
```

Wire-up in `__main__.py`: `_maybe_start_fleetq_bridge(config)` runs in `main()` if `[fleetq] enabled = true AND register_as_bridge = true`. Token resolved from `config.fleetq.api_token_env` (default `FLEETQ_API_TOKEN`). Empty token / missing optional dep / network failure during register → warning + skip, never a hard fail (harbormaster keeps serving its MCP transport regardless).

The bridge's `stop()` runs in a `finally` so the deregister fires whether `mcp.run()` exits cleanly or via exception (Ctrl-C, SIGTERM).

### 2 · `smoke-ui-with-token` CI job

Closed the v1.0.0a5 retro gap: the UI smoke jobs only tested the abort-on-public-bind-without-token path; the actual bearer-auth roundtrip on the UI port wasn't exercised. New CI job sets `HARBORMASTER_UI_TOKEN`, starts the UI on loopback (opt-in path), and asserts no-token=401, wrong=401, correct=200.

`build` now needs `[test, smoke-http, smoke-ui, smoke-ui-auth, smoke-ui-with-token]` — 5 predecessors before any artifact ships.

---

## Real numbers

| Metric | v1.0.0a5 | v1.0.0a6 |
|--------|----------|----------|
| Source files | 21 | 24 (+ `fleetq/{__init__,bridge,heartbeat}.py`) |
| Source LOC | ~1190 | ~1500 |
| Tests | 141 (140 + 1 skip) | 168 (167 + 1 skip) |
| Console scripts | 2 | 2 |
| CI jobs | 6 | 7 (+ smoke-ui-with-token) |
| Optional extras | 3 ([ui], [fleetq], [dev]) | 3 (now used) |
| `mypy --strict` / `ruff` | clean | clean |

Test breakdown of the +27:
- 14 `BridgeClient` tests via `pytest-httpserver` (real httpx → mocked FleetQ HTTP server).
- 13 `HeartbeatLoop` tests via `MagicMock`-backed client (start/stop, periodic heartbeat, re-register on session lost, swallow transient errors, retry initial register, daemon-thread + named).

---

## What worked

- **Discovery first, code second.** Reading the actual FleetQ controller / actions / model BEFORE designing the client took ~10 minutes and produced a clean spec doc. Without it I'd have invented payload shapes; the real contract has subtleties (the heartbeat re-activate behavior, the Redis pre-register endpoints cache, the `disconnect=0` stale-superseded path) that would have leaked into bugs.
- **Sync over async.** FastMCP's stdio transport is sync. Using `threading.Thread` for the heartbeat keeps the bridge integration from leaking asyncio into the rest of the codebase. `httpx.Client` (not `AsyncClient`) is sufficient — heartbeats are once-per-30s, not high frequency.
- **`pytest-httpserver` for the contract surface.** Real httpx client, mocked server. The tests document the wire format — anyone reading them sees the exact bytes harbormaster sends. No "what does FleetQ expect?" guesswork in production.
- **Keep failure modes idempotent.** `disconnect()` returns `0` on stale (200), `0` on already-gone (404), only raises on 500. `heartbeat()` returns `False` on 404 (recoverable, signals re-register), only raises on 500. Loop swallows transient `BridgeError` and retries next tick. Result: the bridge never crashes the harbormaster process — at worst it logs a warning and keeps trying.

## What to change / next

- **Reverse-channel relay is the elephant.** Without it, harbormaster shows up "connected" in FleetQ but every `mcpCall` from FleetQ to a harbormaster tool returns 404 because there's no daemon listening on `private-daemon.<team_id>`. v1.0.0a6 is the visibility milestone; v1.0.0a7+ is the proxy milestone. Plan the Reverb / Pusher private-channel subscription before scoping a7.
- **No CI job exercises the live FleetQ Bridge.** All 27 new tests are mocked. A nightly job that hits a real test FleetQ instance would catch contract drift faster than waiting for the user to notice. Defer until there's actually a test FleetQ instance available.
- **`update_endpoints` is implemented but never called from `__main__`.** v1.0.0a6 announces endpoints once at register and never updates them. If a user adds a new project mid-process, FleetQ won't see it. Tie this to a future "watch config for changes" feature; not blocking.
- **Bridge logging goes to stderr via `logger.info`/`warning` but harbormaster doesn't configure `logging` anywhere.** Means the warnings only show if the user pre-configures Python logging. Worth wiring a minimal `logging.basicConfig` in `__main__.main()` next sprint.

---

## Action items for the next sprint (v1.0.0a7 / week 7)

1. **Reverse-channel relay** — subscribe to `private-daemon.<team_id>` Pusher channel via `pusher-python-server` or the asyncio Pusher client, dispatch incoming MCP tool calls into harbormaster's tool registry, send results back over the channel. The big v1.1 deliverable that turns the v1.0.0a6 visibility into actual proxy capability.
2. **Logging configuration** — `logging.basicConfig` honoring `config.server.log_level`, JSON formatter under `--log-format=json`, structlog optional.
3. **Live FleetQ smoke job** — gated GH Actions workflow that registers a throwaway harbormaster against a test FleetQ, heartbeats once, deregisters. Runs nightly / on-demand.
4. **`update_endpoints` from a config-watch loop** — cheap, reuses the existing client method.
5. **Bump `[fleetq]` extra to actually require `httpx`** — currently the import path is lazy but if the user installs the wrong combo they get an ImportError at runtime instead of at install. Done correctly already — verify in CI.

## Out-of-scope (still)

- Q&A history / federated KG / auto project graph — v1.2 roadmap.
- Backends other than Claude — wait for first user request.
- Plugin / extensions API — v2.
- Tauri / Electron native UI wrapper — post-v1.2.

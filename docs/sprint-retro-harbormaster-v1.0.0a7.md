# Sprint Retro — Harbormaster v1.0.0a7

**Date**: 2026-05-08
**Mode**: continuation of `/sprint-orchestrate full` ("продължи")
**Goal**: tighten the v1.1 surface — operator-visible logging, FleetQ HTTP-tunnel mode unblockers, refactor the wire shape into one place. Defer the reverse WebSocket relay to its own focused sprint.
**Outcome**: ✅ Tagged `v1.0.0a7`. 3 commits. 180 tests pass + 1 intentional skip.

---

## What landed

Three commits on `feat/harbormaster-v1.0.0a7`:

| SHA | Subject |
|-----|---------|
| `e662d2f` | feat(fleetq): /discover + /health endpoints + extracted manifest |
| `591ff85` | feat(logging): configurable logging — text or json, shared across processes |
| (this commit) | ship: bump to 1.0.0a7 + sprint retro |

**Diff vs v1.0.0a6**: ~7 files changed, +470 / −20.

---

## Capabilities (this sprint)

### 1 · Endpoints manifest extracted

`harbormaster.fleetq.endpoints.build_manifest()` is now the single source of truth for the `{agents, llm_endpoints, mcp_servers}` wire shape. Both the Bridge `register` payload and the new `/discover` endpoint go through it. Add a tool to harbormaster, change one constant (`HARBORMASTER_TOOLS`), both wire formats update.

### 2 · `/discover` and `/health` endpoints (FleetQ HTTP-tunnel mode)

```
GET /discover  → {"agents": [], "llm_endpoints": [], "mcp_servers": [{"name": "harbormaster", ...}]}
GET /health    → {"status": "ok", "version": "1.0.0a7"}
```

Closes the gap that v1.0.0a6 left: Bridge integration only worked via the WebSocket-relay path (which we don't have a daemon for). With these two endpoints, a user can now expose harbormaster-ui's port via Cloudflare Tunnel / Tailscale Funnel / ngrok and paste the URL into FleetQ's "Connect a bridge" UI. FleetQ calls `/discover` once for validation, stores the connection, and pings `/health` periodically.

The bearer middleware (when `HARBORMASTER_UI_TOKEN` is set) covers both — FleetQ's optional `endpoint_secret` matches the same env-var.

When the `[fleetq]` extra is not installed, `/discover` falls back to an empty manifest (200) instead of 500. Probes from FleetQ stay clean even on partial installs.

### 3 · Configurable logging (`--log-format text|json`)

`harbormaster.__main__._configure_logging(level, fmt)`. Both `harbormaster-mcp` and `harbormaster-ui` call it on startup with `config.server.log_level` (Literal-validated since v1.0.0a1) and `--log-format`. Text for humans, json for `journalctl` / Docker / k8s.

The Bridge lifecycle events (register / heartbeat / 404-session-lost / re-register / disconnect) are now visible without the operator having to pre-configure Python logging.

---

## Real numbers

| Metric | v1.0.0a6 | v1.0.0a7 |
|--------|----------|----------|
| Source files | 24 | 25 (+ `fleetq/endpoints.py`) |
| Source LOC | ~1500 | ~1700 |
| Tests | 168 (167 + 1 skip) | 180 (179 + 1 skip) |
| MCP-side endpoints | 1 (`/sse`-ish via FastMCP) | 1 unchanged |
| UI endpoints | 3 (`/`, `/api/health`, `/api/projects`) | 5 (+ `/health`, `/discover`) |
| Console scripts | 2 | 2 (both now log-aware) |
| `mypy --strict` / `ruff` | clean | clean |

---

## What worked

- **Discovery before code, again.** Reading `BridgeController::connect` + `ping` told me FleetQ pings `/health` (not `/api/health`) and calls `/discover` on the bridge URL — both routes I'd have missed if I'd just designed from architecture doc §10. Concrete reads of the partner-side controller continue to be the best ROI move on integration sprints.
- **Single-source manifest first.** Extracting `build_manifest()` BEFORE adding `/discover` meant the new endpoint shipped with zero risk of wire-shape divergence from `register`. Two callers, one shape.
- **`pytest.importorskip` keeps tests honest.** The `/discover` test imports `from harbormaster.fleetq import build_manifest` — gated by the [ui] importorskip already at the top of `test_ui.py`. Means the test breaks loud if the [fleetq] extra ever stops shipping `build_manifest`, but stays silent on minimal installs.
- **JSON logging without a dep.** Stdlib `logging.Formatter.format()` + `json.dumps()` is enough. structlog was never going to win this trade — adding a dep for ~30 lines of formatter is gold-plating.

## What to change / next

- **Reverse WebSocket relay is still the elephant.** v1.0.0a7 unblocks REGISTRATION via HTTP-tunnel mode, but FleetQ's `mcpCall` controller still uses the Redis+Reverb relay path for actual tool execution. Without the WebSocket subscriber, `mcpCall` from FleetQ to harbormaster will return 404 even when our HTTP-tunnel registration succeeds. v1.0.0a8 must focus on this — Pusher/Reverb private-channel subscription, frame protocol, dispatch to the local tool registry.
- **`/health` is duplicated logic.** `/api/health` and `/health` return the same payload. Defining them as two separate FastAPI handlers is fine for v1.0 but if a third path joins (e.g. `/healthz` for Kubernetes), refactor to a shared dependency.
- **Logging config is set ONCE at startup.** If the user `kill -HUP`s the process to reload config (we don't support this yet), log_level wouldn't update. Acceptable for v1.0; revisit in v1.2 if the config-watch action item from a6 ever lands.

---

## Action items for the next sprint (v1.0.0a8 / week 8)

1. **Reverse WebSocket relay** (the proxy milestone, finally) — subscribe to `private-daemon.<team_id>` Pusher channel via `pusher-python-server` or `pysher`, dispatch incoming `mcpCall` frames into harbormaster's tool registry, send responses back over the channel. The big v1.1 deliverable that turns "harbormaster shows up in FleetQ Connections UI" into "harbormaster's tools are usable from FleetQ agents".
2. **Live FleetQ smoke job** — gated nightly job that registers a throwaway harbormaster against a test FleetQ instance. Tied to whether a test instance is available; defer if not.
3. **`update_endpoints` from a config-watch loop** — still on the list since a6. Smaller of the two FleetQ tasks.
4. **Reduce `/health` duplication** if v1.0.0a8 adds another health-style probe path.

## Out-of-scope (still)

- Q&A history / federated KG / auto project graph — v1.2 roadmap.
- Backends other than Claude — wait for first user request.
- Plugin / extensions API — v2.
- Tauri / Electron native UI wrapper — post-v1.2.

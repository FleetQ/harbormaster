# Sprint Retro — Harbormaster v1.0.0a4

**Date**: 2026-05-08
**Mode**: continuation of `/sprint-orchestrate full` ("Продължи със следващото")
**Goal**: ship the Live UI scaffold + auth + CI live-SSE; defer FleetQ Bridge & PyPI publish to v1.0.0a5
**Outcome**: ✅ Tagged `v1.0.0a4`. 5 commits. 128 tests pass + 1 intentional skip.

---

## What landed

Five commits on `feat/harbormaster-v1.0.0a4`:

| SHA | Subject |
|-----|---------|
| `884b3f4` | refactor(backends): promote `get_backend` to public API |
| `3a35c35` | feat(transport): bearer-token auth required for HTTP/SSE |
| `11d7647` | ci: smoke-http job — live SSE + bearer on every push |
| `f176432` | feat(ui): Live UI scaffold — dashboard + API endpoints |
| (this commit) | ship: bump to 1.0.0a4 + sprint retro |

**Diff vs v1.0.0a3**: ~12 files changed, +750 / −20.

---

## Capabilities (this sprint)

### 1 · `get_backend` promoted to public

`harbormaster.backends.get_backend(config, name="claude")`. Closes the v1.0.0a3 retro nit about `_get_backend` being de-facto public via cross-module imports. Two lines per call site updated; behavior identical.

### 2 · Bearer-token auth for HTTP/SSE

There is no auth-disabled HTTP mode in v1.0. `harbormaster-mcp --transport sse|streamable-http` reads `HARBORMASTER_MCP_TOKEN` (env-var name overridable via `--auth-token-env`), exits 2 with a `python -c 'secrets.token_urlsafe(32)'` recipe if empty, and rejects every non-matching `Authorization: Bearer ...` header with 401. Stdio transport remains process-bound and ignores auth.

New `src/harbormaster/transport.py` module owns: token resolution, the Starlette `BaseHTTPMiddleware` subclass, and uvicorn launch. `__main__.py` no longer calls `mcp.run(transport=...)` for HTTP; it goes through `mcp.{sse,streamable_http}_app()` + middleware + uvicorn directly.

### 3 · CI live-SSE smoke job

New job in `.github/workflows/ci.yml`: generate a token, start `harbormaster-mcp --transport sse` in background, poll until `/sse` returns 401 (= server up + middleware live), assert no-token / wrong-token both 401, assert correct-token is *not* 401. The build job now `needs: [test, smoke-http]` so artifacts only ship when both pass.

### 4 · Live UI scaffold

`harbormaster-ui` console script. FastAPI + Jinja2, HTMX + Alpine + Tailwind via CDN. Three routes:

- `GET /` — dashboard with Alpine-driven project grid.
- `GET /api/projects` — JSON list of `ProjectInfo` dicts.
- `GET /api/health` — `{status, version}`.

Separate process from the MCP server. Both processes read the same TOML config; SSE feed of live MCP queries lands in v1.0.0a5.

---

## Real numbers

| Metric | v1.0.0a3 | v1.0.0a4 |
|--------|----------|----------|
| Source files | 16 | 21 |
| Tests | 109 (108 + 1 skip) | 129 (128 + 1 skip) |
| Console scripts | 1 (`harbormaster-mcp`) | 2 (+`harbormaster-ui`) |
| MCP transports | 3 (stdio + sse + streamable-http) | unchanged |
| HTTP transport auth | none | required bearer |
| CI jobs | 2 (test, build) | 3 (+ smoke-http) |
| FastAPI routes | 0 | 3 |

---

## What worked

- **Five separate commits, five distinct concerns.** Each commit reviewable in isolation; no commit dragged in tangential changes. `git log` reads as a narrative.
- **The Starlette TestClient pattern** for the bearer middleware was the key unlock for testing a Starlette concern without spinning up a real server. Same trick worked for the FastAPI UI routes (FastAPI uses Starlette's TestClient under the hood).
- **CI smoke-http job design**: generate a one-shot token, poll the 401 path to confirm the server is *and* the middleware is live, then test all four auth states. No flakiness — the 401-on-empty-auth pattern is a fast, reliable readiness check.
- **`pytest.importorskip('fastapi')`** in `test_ui.py` cleanly handles contributors who run only stdio tests. CI installs `--extra dev` (which now includes `fastapi`/`jinja2`/`httpx`) so the tests always run there.
- **Lazy vs eager imports** got an explicit decision this sprint. Routes that participate in FastAPI dependency injection need eager imports (PEP 563 + `get_type_hints()` collision); other UI files can stay lazy. Decision documented inline so the next maintainer doesn't re-litigate it.

## What to change / next

- **Live UI has no SSE yet.** Architecture doc §4 calls for a live query feed; v1.0.0a4 is static-fetch only. Next sprint introduces an event broadcast inside the MCP server and a `/api/events` SSE endpoint that the dashboard's Alpine `x-init` subscribes to.
- **Auth applies to the MCP HTTP transport, not the UI.** The `/api/projects` endpoint is wide open right now. For local-only `127.0.0.1` use that's fine; for any deployment that exposes the UI, we'll want the same bearer-token middleware reused in `harbormaster-ui`. Trivial wiring once we factor `transport.build_bearer_middleware` into a shared util.
- **Static directory ships empty.** `app.py` only mounts `/static` if the directory exists. We should either delete the empty dir or commit a `.gitkeep` + a placeholder asset so the mount is meaningful. Currently it's a no-op — fine, but inelegant.
- **`harbormaster-ui` smoke test is unit-only.** Unlike `harbormaster-mcp` which has a CI live-SSE job, the UI relies on TestClient unit tests. Adding a `smoke-ui` CI job that hits `/api/health` would mirror the MCP smoke pattern.

---

## Action items for the next sprint (v1.0.0a5 / week 5)

1. **SSE feed in the Live UI** — `/api/events` server-sent events stream. Backed by an in-process pub/sub: every MCP tool invocation broadcasts a `query_started` / `query_completed` event; the dashboard subscribes via `EventSource` and updates its in-flight pane.
2. **FleetQ Bridge integration** (architecture doc §10) — discover the Bridge contract from `agent-fleet/cloud/routes/api.php`, implement `register` / `heartbeat` / `deregister`, gate behind `[fleetq] enabled = true`. v1.1 phase officially kicks off here.
3. **Reuse bearer middleware on the UI** — same env-var pattern, exits-with-recipe behavior. Required before any deployment exposes the UI port.
4. **PyPI publish trigger** in CI on tag push, gated by GitHub environment + `PYPI_API_TOKEN` secret. Once `v1.0.0a5` lands and the FleetQ Bridge proves out the integration story, flip the switch.
5. **`smoke-ui` CI job** — start `harbormaster-ui`, hit `/api/health`, assert 200 + JSON shape.
6. **Static dir cleanup** — either drop the conditional mount or commit a real placeholder asset.

## Out-of-scope (still)

- Q&A history / federated KG / auto project graph — v1.2 roadmap.
- Backends other than Claude — wait for first user request.
- Plugin / extensions API — v2.
- Tauri / Electron native UI wrapper — post-v1.2.

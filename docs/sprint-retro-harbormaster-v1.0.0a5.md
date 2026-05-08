# Sprint Retro — Harbormaster v1.0.0a5

**Date**: 2026-05-08
**Mode**: continuation of `/sprint-orchestrate full` ("продължи")
**Goal**: ship the security + CI hardening track from the v1.0.0a4 retro; defer FleetQ Bridge and SSE feed to v1.0.0a6+
**Outcome**: ✅ Tagged `v1.0.0a5`. 4 commits. 140 tests pass + 1 intentional skip. Release pipeline ready (manual PyPI setup pending).

---

## What landed

Four commits on `feat/harbormaster-v1.0.0a5`:

| SHA | Subject |
|-----|---------|
| `3a10fa0` | feat(ui): bearer auth on UI port + static dir cleanup |
| `096c71e` | ci: smoke-ui + smoke-ui-auth jobs — UI live-stack on every push |
| `8ba49aa` | ci: PyPI publish workflow via Trusted Publishing (OIDC) |
| (this commit) | ship: bump to 1.0.0a5 + sprint retro |

**Diff vs v1.0.0a4**: ~7 files changed, +470 / −15.

---

## Capabilities (this sprint)

### 1 · UI bearer auth (loopback-vs-public policy)

`harbormaster-ui` now mirrors the auth UX of `harbormaster-mcp` for HTTP transport, with one explicit relaxation:

- **Loopback bind** (`127.0.0.1` / `localhost` / `::1`): bearer token **optional**. Set `HARBORMASTER_UI_TOKEN` to opt in even on loopback; leave unset for solo-dev open access.
- **Public bind** (anything else): bearer token **required**. Empty env var → exit 2 with a `secrets.token_urlsafe(32)` recipe — same UX as MCP HTTP transport.

The middleware itself is reused from `harbormaster.transport.build_bearer_middleware` — same code path that protects the MCP HTTP/SSE transport. Bearer-auth surface is implemented exactly once.

### 2 · Static dir cleanup

`src/harbormaster/ui/static/` removed (empty since v1.0.0a4) and the conditional `StaticFiles` mount in `app.py` deleted. All UI assets are CDN-loaded via `base.html`. When v1.0.0a6+ ships local assets we'll re-add the dir and the mount in the same commit, with content.

### 3 · CI smoke-ui jobs

Two new CI jobs (after `test`, before `build`):

- **`smoke-ui`** — start `harbormaster-ui --host 127.0.0.1 --port 17531` in background, poll `/api/health` for 200, assert body has `"status":"ok"` + `"version"` field, assert `/api/projects` returns 200 JSON array, assert `/` returns HTML with `<title>` + "Harbormaster" + Tailwind CDN tag.
- **`smoke-ui-auth`** — `harbormaster-ui --host 0.0.0.0 --port 17532` with no `HARBORMASTER_UI_TOKEN` must exit 2 BEFORE binding. Catches a regression where a public port could bind unauthenticated.

`build` job now needs `[test, smoke-http, smoke-ui, smoke-ui-auth]`. Artifacts only ship when both processes (MCP HTTP + UI) and both auth guards pass live.

### 4 · PyPI publish workflow (Trusted Publishing / OIDC)

`.github/workflows/publish.yml` — no long-lived API tokens in the repo. Tag pushes to `v*` trigger build + publish; the build job verifies that `harbormaster.__version__` matches the pushed tag (strips leading `v`) before any upload.

Triggers:
- `push` tags `v*` → publish to PyPI (production).
- `workflow_dispatch` → manual run, choose `pypi` or `testpypi`.

`docs/publishing.md` documents the one-time setup: register the project on PyPI, configure Trusted Publishing for `FleetQ/harbormaster` + workflow `publish.yml` + environment `pypi`, optionally add manual-approval rules.

---

## Real numbers

| Metric | v1.0.0a4 | v1.0.0a5 |
|--------|----------|----------|
| Source files | 21 | 21 (no new modules; UI+transport refactored) |
| Tests | 129 (128 + 1 skip) | 141 (140 + 1 skip) |
| Console scripts | 2 | 2 (auth-aware) |
| CI workflows | 1 (`ci.yml`) | 2 (+ `publish.yml`) |
| CI jobs | 3 | 6 (+ smoke-ui, smoke-ui-auth, publish) |
| HTTP/UI auth posture | MCP only | MCP + UI |

---

## What worked

- **Reusing `transport.build_bearer_middleware` on the UI app**. One implementation, two callers, identical 401 semantics. The UI auth test even exercises the same middleware via FastAPI's TestClient — proves the module boundary holds.
- **Loopback-vs-public policy as a single decision point**. `_resolve_ui_token` returns either a token or "" or exits — three states, eight test cases (incl. localhost / `::1` / whitespace-only token), zero ambiguity.
- **Tag-vs-package version assertion** in `publish.yml`. Catches the embarrassing release where someone tags `v1.0.0a5` while `__init__.py` still says `1.0.0a4`. Cheap insurance.
- **Trusted Publishing over a long-lived token** for PyPI. No secret to rotate, no leak surface, no `PYPI_API_TOKEN` in a vault. Setup is one-time on PyPI.org's UI.
- **`smoke-ui-auth` as a regression catcher** specifically for the auth guard. The risk that v1.0.0a5 most needs to defend against is a future commit accidentally letting a public port bind without a token. This job's only job is catching that.

## What to change / next

- **PyPI setup is still manual** — the workflow will land but the first tag push triggers a publish that will fail until the user goes to PyPI.org and configures Trusted Publishing. Document this in the release notes so it's not a surprise. Better: add a `gh issue create` step on first failure that opens an issue with the setup steps.
- **No live token roundtrip test for UI auth.** `smoke-ui` runs without a token (loopback, allowed). A `smoke-ui-with-token` job that sets `HARBORMASTER_UI_TOKEN` and asserts 401-without-bearer + 200-with-bearer would mirror `smoke-http` more faithfully. Adds 30s of CI time; worth it.
- **`harbormaster-mcp --transport stdio` still skips auth entirely.** Documented as intentional (process-bound, whoever spawns owns it), but a future hostile-MCP scenario could exploit a user mounting our stdio MCP into an untrusted client. Not in scope for v1.0; flag for v2 threat model.
- **Two console scripts, two auth env vars, two policies.** Simple to reason about now; if a v1.1 introduces a third process (background trajectory writer? FleetQ Bridge daemon?) we'll want a single `auth.py` module that owns env var naming + policy lookup. Don't extract until 3 callers exist.

---

## Action items for the next sprint (v1.0.0a6 / week 6)

1. **FleetQ Bridge integration** (architecture doc §10) — discovery from `agent-fleet/cloud/routes/api.php` Bridge controller, then implement `register` / `heartbeat` / `deregister` lifecycle, gated behind `[fleetq] enabled = true` config. v1.1 phase officially kicks off.
2. **Reuse Bridge contract for first `[fleetq]` adapter test** — register a fake harbormaster instance against a mocked FleetQ HTTP server (`pytest-httpserver`), assert the heartbeat shape matches what FleetQ expects.
3. **`smoke-ui-with-token` CI job** — same pattern as `smoke-http`, adds the missing token roundtrip test.
4. **Manual PyPI setup** — one-time on the user's side: register `harbormaster-mcp`, configure Trusted Publishing, create GH `pypi` environment. Then v1.0.0a6 is the first tag that actually publishes.
5. **A regression test for the security commit** — `tests/integration/test_security_invariants.py`: feed adversarial project names through every callsite, assert no path leaves the configured base. Catches future refactors that drop the validation.

## Out-of-scope (still)

- SSE feed in the Live UI — needs trajectory storage (v1.2 territory) or a synthetic-tick demo. Either way: separate sprint.
- Q&A history / federated KG / auto project graph — v1.2 roadmap.
- Backends other than Claude — wait for first user request.
- Plugin / extensions API — v2.

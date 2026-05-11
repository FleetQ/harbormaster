# Harbormaster v21.0.0 — QA + Security Report

**Date:** 2026-05-11
**Reviewer:** Claude Opus 4.7 (1M context) via `/qa full` + `/security-review`
**Scope:** Full project at `~/htdocs/harbormaster` (commit `b6ac6f01`, tag `v21.0.0`)

---

## TL;DR

Ship-able **on PyPI**, but **CI has been red on every `main` commit for the entire v21 sprint** (>=20 consecutive failed runs), the v21 retro's "all green" claim is inaccurate, and the **dashboard ships a JS exception on every page load**. Security review found **0 critical, 1 HIGH, 4 medium**, with broad positive coverage on the defensive primitives.

---

## CRITICAL

_None._

## HIGH

### H1. CI red on every `v21.x.x` GA — published anyway

Every commit on `main` since at least `4cf25ea0` (v19->v20 boundary) shows `CI = failure` on GitHub Actions. The test matrix (Ubuntu+macOS x py3.11/3.12/3.13) consistently fails, which cascades into all downstream smoke jobs being **skipped**. `Publish to PyPI` ran independently on each tag push (Trusted Publishing on tag, no `needs:` on CI), so the red GAs reached PyPI — v21.0.0 is currently the published latest.

The v21 sprint retro memory claimed "1926 tests passing, 8 CI jobs green". Reality: ~50 failures + 16 errors locally, matching the CI failure surface.

**Fix:** Gate `publish.yml` on `CI` workflow success (add `workflow_run` trigger with `conclusions: [success]`). Then triage the failures below.

### H2. Non-constant-time bearer/cookie token comparison

`src/harbormaster/transport.py:80,90` uses Python `!=` for token comparison in `BearerAuthMiddleware.dispatch`. Timing-side-channel feasibility is low (HTTPS jitter, loopback-only by default) but exposed on any non-loopback bind.

**Fix:** `import hmac; hmac.compare_digest(authz, expected_header)` and same on the cookie path.

### H3. Dashboard ships an Alpine ReferenceError on every load

`http://127.0.0.1:7531/` — browser console:

```
[EXCEPTION] Uncaught ReferenceError: pluginCount is not defined
  Expression: "`${pluginCount || 0} plugin${pluginCount === 1 ? '' : 's'} discovered`"
```

The `pluginCount` symbol is referenced in a child Alpine binding without being defined in the parent `x-data` scope. Likely a refactor leftover from the v21.a3 OKLCH accent picker or v20.x plugins tab work.

**Fix:** Grep `pluginCount` in `src/harbormaster/ui/templates/`, ensure it's declared in the enclosing `x-data` or replace with the correct property name (likely `plugins.length` from the `/api/plugins` payload).

---

## MEDIUM

### Tests (50 failed + 16 errored locally; same on CI)

| File | Failures | Root cause |
|---|---|---|
| `tests/unit/test_bridge.py` (16 errors) | ScopeMismatch | `pytest-base-url` `_verify_url` fixture is session-scoped; `base_url` here is function-scoped. Either elevate to session scope or remove `pytest-base-url` plugin. |
| `tests/unit/test_fan_out.py` | `test_fan_out_ask_signature` | v21.0.0a10 added `model` arg to `fan_out_ask` but didn't update the expected-keys set. |
| `tests/unit/test_ui.py` (3) | `fake_stream got unexpected keyword 'model'` | Same v21.0.0a10 regression — fake stream stubs need to accept `model=`. |
| `tests/ui/test_a11y_floor.py` | `icon-only buttons missing aria-label` in `dashboard.html` | A11y regression on dashboard. Add aria-label to the icon-only buttons surfaced by the test. |
| `tests/unit/test_config_doc_reference.py` | `undocumented config fields` | Config doc parity drift — a recently added field is missing from operator docs. |
| `tests/unit/test_v15_precommit_integration.py` + `test_v16_precommit_polish.py` | `parity script failed` | Pre-commit parity script asserts against state that no longer matches. |
| `tests/ui/test_browser_smoke.py` | Playwright strict mode violation | Selector `text=FleetQ Bridge` now matches 2 elements (heading + sidebar). Use `get_by_role("heading", name="FleetQ Bridge")` or `.first()`. |
| `tests/ui/test_screenshot_diff/test_screenshots.py` | `wait_for_load_state("networkidle", 5000) timeout` | UI never reaches network-idle — likely the running heartbeat / SSE keep-alive prevents quiescence. Either mock the heartbeat in tests or switch to `wait_for_load_state("domcontentloaded")`. |

### Security mediums (from security-engineer audit)

- **M1.** Plugin entry-point loader passes full `HarbormasterConfig` (incl. `FLEETQ_API_TOKEN`) to allowlisted plugins. Intended trust model — needs an explicit callout in `docs/operator-guide.md`: "allowlisting a plugin = giving it your tokens."
- **M2.** `_atomic_write` in `src/harbormaster/ui/routes.py:2135` chmods written memory files to `0o644` regardless of umask. On a multi-user host, other users can read project memory contents (which may contain prompt/QA traces echoing secrets). **Fix:** `0o600`, or preserve the existing file's mode.
- **M3.** `register_fn(mcp, config)` is wrapped in `try/except Exception` in `src/harbormaster/plugins.py:138-145`. A failing plugin's partially-registered tools / monkey-patches are not rolled back. Low likelihood given the allowlist gate.
- **M4.** `urllib.request.urlopen(endpoint)` in `dispatcher_cli.py:160` follows redirects by default. `endpoint` is operator-supplied so SSRF risk is operator-level only, but pin a `Request` with a fixed-scheme opener if this surface ever reaches a UI input.

---

## LOW

- **L1.** `BackendError` echoes up to 500 bytes of remote stderr in `claude.py:155-156` / `codex.py:225-226`. Acceptable for operator-facing MCP, sanitise if surfaced to end users.
- **L2.** `pysher>=1.0` extra pin can latch onto buggy versions (the documented Thread-init crash). Pin `==1.0.8` or known-good range. `onnxruntime<1.26` is already correctly pinned per recorded learning.
- **L3.** Cookie `hm-auth` `secure` flag is conditional on `request.url.scheme == "https"`. Behind a TLS-terminating proxy this requires uvicorn `--proxy-headers` to be enabled to honour `X-Forwarded-Proto`. Document this in the operator guide.

---

## Clear (audited — solid)

The security-engineer audit explicitly cleared the following primitives:

- SSH command construction (`ssh.py` — `shlex.quote` everywhere, `BatchMode=yes`, `ConnectTimeout`)
- Backend remote command builders (`backends/claude.py`, `codex.py` — every dynamic value quoted, prompt after `--` to neutralise leading-dash injection, local `ask_local` uses argv-list `subprocess.run`)
- Model whitelist (`_resolve_model` in both backends, with operator-set deny override)
- Project name regex + post-resolve containment check (`projects.py:31, 212-224`)
- Memory editor path safety (strict allowlist, regex, `..` rejected, post-resolve containment, atomic tmp+rename)
- Markdown XSS pipeline (`bleach.clean` with explicit tag/attr/protocol allowlist — `javascript:`, `data:`, `vbscript:` stripped; no `|safe` anywhere)
- `tojson` in HTML attribute (Jinja2 >=2.9 escapes `<>&'` as `\u`-style — neutralises v19->v21 retro pitfall)
- Cookie SSE auth (`httponly`, `samesite=strict`, conditional `secure`, 12h TTL)
- Static file serving (`..` + absolute-path guard, `resolve()` + containment)
- Plugin entry-point loader (deny-by-default verified: `enabled=False` no-op; empty `allow` rejects everything)
- No unsafe deserialization paths (`json.loads` only across backends/history/fleetq)
- FleetQ HTTP client SSRF (`base_url` from operator TOML only)
- HTTP transport auth enforcement (`require_auth_token_or_exit` — verified 401 on no-auth, 404 with auth = `/health` not exposed on MCP HTTP, that's expected — MCP HTTP serves `/mcp/*`)

---

## Backend gates

| Check | Result |
|---|---|
| `ruff check src/ tests/` | All checks passed |
| `mypy --strict src/harbormaster/` | Success: no issues found in 58 source files |
| `pytest tests/` | **1838 passed, 50 failed, 2 skipped, 16 errored** |
| `harbormaster-mcp --version` | `21.0.0` (matches PyPI) |

## API smoke

| Endpoint | Status | Note |
|---|---|---|
| `GET :7531/api/health` | `200 {"status":"ok","version":"21.0.0"}` | OK |
| `GET :7532/health` (no auth) | `401` | Auth gate works |
| `GET :7532/health` (with token) | `404` | Expected — MCP HTTP serves `/mcp/*`, not `/health` |

## Frontend smoke

UI loads, all expected interactive surfaces present (sidebar, project filter, theme toggle, accent picker, Quick Ask, fan-out form, inspector). **One uncaught JS exception** on dashboard load — see H3.

---

## Recommendations (in order)

1. **Fix H3** (Alpine ReferenceError) — 1-line fix, visible to every operator.
2. **Fix H2** (`hmac.compare_digest`) — 2-line fix in `transport.py`.
3. **Fix the test suite** — same fixes will close H1 since they're the CI failures too. Order: fan_out signature -> test_ui stream stubs -> test_bridge fixture scope -> a11y aria-labels -> browser_smoke selectors -> screenshot test wait condition -> config doc parity.
4. **Gate `publish.yml` on `CI` success** — prevents future red-GA shipping.
5. **Address M2** (`0o600` for memory files) and document M1/L3.
6. **Optionally**: pin `pysher==1.0.8`, address M4 + L1 if reaching wider audience.

---

## Verdict

- **Code surface**: ship-able security-wise (1 HIGH is a 2-line fix; everything else is hygienic)
- **CI/test health**: **NOT** ship-able as-is — red CI on every recent GA is a process bug, the v21 retro's claim of "all green" is inaccurate
- **User-visible regression**: dashboard JS exception on every load is unacceptable for "GA" status

Recommend a `v21.0.1` patch with the H2 + H3 + test fixes before any v22 work begins.

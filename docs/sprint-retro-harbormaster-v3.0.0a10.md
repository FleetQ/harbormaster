# Sprint Retro — Harbormaster v3.0.0a10

**Date:** 2026-05-09
**Theme:** Closed the v2.1 UI testing gap. Real Chromium drives the
dashboard / project_detail / fan-out flows in CI now, not just curl
against `/api/health`.

## What landed

### `harbormaster` (this repo)

| SHA | Subject |
|-----|---------|
| `2f63de1` | feat(ui): headless browser tests via Playwright (v3.0.0a10) |

(Final SHA replaced in the ship commit's CI verification.)

## Capabilities (this sprint)

### 1 · `[ui-test]` extra

```toml
ui-test = [
    "playwright>=1.45",
    "pytest-playwright>=0.5",
]
```

Operators install separately because Playwright pulls a ~150MB
Chromium binary that doesn't belong in the default `[dev]` extra.

```bash
uv sync --extra dev --extra ui-test
uv run playwright install chromium
uv run pytest -m browser tests/ui/
```

### 2 · `pytest -m browser` marker

`browser` registered in `pyproject.toml`:

```toml
[tool.pytest.ini_options]
markers = ["browser: requires Playwright + chromium (gate with -m browser)"]
```

Combined with module-level `pytest.importorskip("playwright")` in
`tests/ui/test_browser_smoke.py`, the regular suite is unaffected
when the extra isn't installed.

### 3 · Session-scoped `ui_url` fixture

`tests/ui/conftest.py` boots `harbormaster-ui` once per pytest
session on a random loopback port (binds-to-zero pattern), polls
`/api/health` for readiness (10s timeout), yields the URL, and
terminates on teardown. Per-session state lives in `tmp_path`
config so successive runs don't leak.

### 4 · 7 browser-driven smoke tests

```
tests/ui/test_browser_smoke.py::
  test_dashboard_renders_header
  test_dashboard_renders_bridge_status_panel
  test_dashboard_lists_seeded_project
  test_dashboard_card_ask_button_toggles_form          # v3.0.0a7
  test_fan_out_page_loads_with_form
  test_fan_out_url_state_round_trip                    # v3.0.0a9
  test_meta_tag_absent_when_no_auth_token              # v3.0.0a6 negative
```

### 5 · CI smoke-ui-browser job

`.github/workflows/ci.yml` `smoke-ui-browser`: Ubuntu 24.04,
installs `[ui-test]`, runs `playwright install --with-deps chromium`,
then `pytest -m browser tests/ui/`. Added to `build`'s `needs`
chain so a browser-test regression blocks artifact build.

## Real numbers

- 1/1 v3.0.0a9-retro action item shipped
- 0 PRs opened — merged `feat/v3.0-playwright` directly via `--no-ff`
- 7 new browser tests (skipped locally when playwright is absent)
- Test suite delta: 621 + 1 skip → **621 + 2 skips** (browser tests
  module-skipped; +0 unit tests intentionally — this sprint is
  scaffolding)
- `mypy --strict` clean across 48 source files
- `ruff` clean across `src/` and `tests/`
- 1 new CI job (smoke-ui-browser); now 9 jobs total per push

## What worked

- **Subprocess fixture, not in-process app.** Browser tests must hit
  a real bind port — TestClient won't do. Booting the actual
  `harbormaster-ui` console script in a subprocess matches the
  production code path (CLI arg parsing, uvicorn boot, real bind).
  Slight startup cost amortised over a session-scoped fixture.
- **Random port via bind-to-zero.** `s.bind(("127.0.0.1", 0))` then
  `getsockname()` — race-free port allocation. No collisions with
  17531-17534 reserved by the curl smoke jobs.
- **`importorskip` at module level.** Single skip on the whole
  module when playwright isn't installed, cleaner than per-test
  pytest.skip calls.

## What to change / next

- **Smoke tests, not coverage.** The 7 tests cover "does the page
  render and respond to one click" — they don't exercise SSE
  streams, fan-out submissions, or trajectory refresh end-to-end.
  Browser tests are slow; covering more flows here trades speed
  for confidence. Defer expansion to v3.x maintenance.
- **No mocked LLM backend.** A real `ask_project` SSE test would
  spawn `claude --print` on the CI runner and either succeed (if
  the runner has Claude credentials) or fail. Skipping that test
  for now keeps the smoke job hermetic.
- **CI runtime cost.** Playwright Chromium install via
  `--with-deps` adds ~30s to the smoke-ui-browser job. Acceptable
  trade-off; `actions/cache` could speed up cold starts.

## Action items for v3.0.0 GA

1. **Drop alpha + write GA retro.** Bump `__version__` to `3.0.0`,
   write a GA retro covering all 10 phases (a1-a10), tag `v3.0.0`,
   push, verify on PyPI. No new code in the GA tag (mirrors v1.0.0
   + v2.0.0 + v2.1.0 GA pattern).

## Out-of-scope (still)

- Tauri / Electron desktop UI — no demand.
- Relay-binary path (Path B) — Path C HTTP tunnel covers it.
- IDE extension — MCP works with any MCP client.
- pnpm v5 lockfile support — pre-2022 format.
- Multi-worker dispatch pool — defer until thread-safety proven.
- Session-cookie auth + CSRF — defer until multi-operator UI is real.
- Per-card host selector — fan-out covers cross-host.
- Mermaid pinch-zoom — pan + 60vh sufficient for now.
- URL state on recall / dashboard — fan-out has highest share value.
- LLM-mocked end-to-end SSE browser tests — hermetic-CI trade-off.

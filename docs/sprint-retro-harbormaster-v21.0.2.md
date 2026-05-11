# Sprint Retro — Harbormaster v21.0.2 (patch)

**Released:** 2026-05-11
**Type:** Patch — operator-initiated follow-up to v21.0.1
**Branch flow:** Directly on `main`

## Why this patch exists

Two threads converged into v21.0.2:

1. **v21.0.1's `verify-ci` gate correctly blocked PyPI publish.** Test
   matrix + smoke jobs went green, but `Headless browser tests
   (Playwright)` was still red — the gate worked as designed and held
   v21.0.1 out of PyPI. We need to either fix Playwright or retire it;
   the operator chose retire.
2. **A `/perf frontend` audit on `:7531`** flagged that `/api/graph`
   takes ~1.9 s in isolation and **blocks the asyncio event loop**, so
   every other `/api/*` call on the cold dashboard serializes behind
   it (~5.8 s effective). Aggregate cold load fires 44 fetches with 6×
   duplicates of `/api/projects` and `/api/network/events`. See
   `docs/perf-report-frontend-2026-05-11.md`.

## Fixes shipped

### Playwright suite retirement

The browser-driven test layer was repeatedly fragile (strict-mode
locator drift, network-idle timeouts on SSE-heavy pages, dependency
weight of Chromium in CI). Retired in full:

- **Deleted**: `tests/ui/test_browser_smoke.py`,
  `tests/ui/test_v19_three_column_shell.py`, `tests/ui/conftest.py`
  (only Playwright `ui_url` fixture), and the entire
  `tests/ui/_screenshot_diff/` directory (test_screenshots.py,
  helper.py, test_helper_unit.py, conftest.py, baseline/).
- **pyproject.toml**: removed `[ui-test]` extra (playwright,
  pytest-playwright, Pillow) and the `markers = ["browser: ..."]`
  pytest config block.
- **.github/workflows/ci.yml**: deleted `smoke-ui-browser` job and
  `screenshot-autobootstrap` job. `build` job's `needs:` updated to
  drop `smoke-ui-browser`.

What replaces them: the existing non-browser UI tests
(`test_a11y_floor.py` HTML-static analysis, `test_cookie_auth.py`,
`test_dispatcher_*_endpoint.py`, etc.) plus the smoke jobs that boot
the real UI process and exercise it via curl. The dashboard JS
behaviour is now exercised end-to-end through those smoke jobs and
through normal operator use, not through scripted Playwright clicks.

If visual-regression coverage becomes a real operator need, the
recommended path is a separate `harbormaster-screenshot-bot` repo
(stable, opt-in) rather than re-introducing Playwright into the main
test surface.

### Perf: `/api/graph` thread offload + 60s TTL cache

Combined fix in `src/harbormaster/ui/routes.py`:

1. The lockfile-walking work (`discover_projects` +
   `build_graph` + lockfile parse) now runs in `asyncio.to_thread(...)`
   so the event loop stays responsive while filesystem I/O runs on a
   worker thread.
2. Payload is cached in-process keyed by
   `(include_dev_deps, transitive, format)` with a 60-second TTL.
   Dependency graphs change on human timescales (project add/remove,
   manifest edit) — 60 s is well below any noticeable staleness while
   eliminating all hot-path disk work.

Verified live on dev UI:

| Call | Before | After |
|---|---:|---:|
| `/api/graph` solo (cold) | 1.93 s | 1.97 s (computed in thread) |
| `/api/graph` solo (warm, in TTL) | 1.93 s | **0.001 s** |
| `/api/projects` while `/api/graph` runs | ~5.8 s | **0.013 s** |
| 3× concurrent `/api/graph` | serialised | 0.018 s each (all cached) |

The cold-path `/api/graph` still takes ~2 s of wall time, but that's
now thread time, not event-loop time, so the rest of the dashboard
loads in parallel.

## What I didn't touch (deferred)

From the perf report:

- **#3 lazy-load `/api/graph` on tab activation** — would shave another
  ~2 s off cold landing on dashboard. Worth a v21.0.3.
- **#4 `Alpine.store('hmData')` to dedupe overlapping fetches** —
  6× duplicate `/api/projects` etc. Bigger refactor; not in scope.
- **#5 sidebar collapse-by-default beyond N projects** — HTML payload
  is 191 KB on the cold response. UI patch, deferred.
- **#6 inspector lazy-mount** — pairs with #5.

## Verification

- `ruff check src/ tests/` — clean
- `mypy --strict src/harbormaster/` — clean (58 source files)
- `pytest tests/` — **1888 passed, 1 skipped, 0 failed, 0 errored**
- Live UI on `:7541` re-validated:
  - `/api/graph` cold: 1.97 s (thread)
  - `/api/graph` warm (cache): 1 ms
  - `/api/projects` during `/api/graph` cold: 13 ms (event loop unblocked)

## v21.0.1 → v21.0.2 process note

v21.0.1's `verify-ci` gate did exactly what it was built to do — caught
a red CI run before it reached PyPI. v21.0.1 is tagged on GitHub but
NOT on PyPI; v21.0.2 supersedes it. The tag stays for historical
reference; no force-push, no yank.

## Chain status

Still HALTED. v21.0.2 is the second operator-initiated patch in the
2026-05-11 audit cycle. Future work continues as patches on `main` for
discrete fixes, or a fresh `feat/v22.0-*` line for a new feature.

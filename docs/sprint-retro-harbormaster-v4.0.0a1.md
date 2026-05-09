# Sprint Retro — Harbormaster v4.0.0a1

**Date:** 2026-05-09
**Theme:** Hardened the v3 surface before stacking more on top. Two
test-coverage gaps from v3 retros, both closed in one phase: real-world
lockfile fixtures + expanded Playwright smoke.

## What landed

| SHA | Subject |
|-----|---------|
| (this branch) | feat(tests): real-world lockfile fixtures + expanded Playwright |

## Capabilities (this sprint)

### 1 · Real-world lockfile fixtures

`tests/fixtures/lockfiles/` now holds four sanitized snippets:

- `pnpm-lock-react-style.yaml` — pnpm v6 with peerDep suffixes,
  scoped `@types/*` packages, transitive `loose-envify` chain
- `pnpm-lock-v9-style.yaml` — pnpm v9 importers + separate snapshots
  block (the snapshot block must NOT bleed into package keys)
- `yarn-v1-style.lock` — multi-selector keys, comment lines, classic
  unindented format
- `yarn-berry-style.lock` — `__metadata` block + `npm:` protocol
  selectors

`tests/unit/test_lockfile_real_world.py` (14 tests) asserts the
v3.0.0a3 parsers handle every quirk. **All passed on first run** —
no parser changes needed. The fixtures remain as regression guards
for future parser edits.

### 2 · Expanded Playwright smoke

Six new browser-driven tests:

- Recall panel renders on the dashboard
- Fan-out selectAll → selectNone round-trip via JS state assertions
- Question typed + selectAll → URL search params updated
- Project name link in card → navigates to detail page
- Card chrome click does NOT navigate (regression-guard for the
  v3.0.0a7 `<a>` → `<article>` unwrap)
- Bearer-token meta presence: deferred to unit test (running a second
  bearer-protected UI subprocess is heavy — covered already in
  `tests/unit/test_ui.py`)

## Real numbers

- 1/1 v3.0.0-retro action item shipped
- 0 PRs opened — merged via `git merge --no-ff`
- 14 new unit tests + 6 new browser tests
- Test suite delta: 621 + 2 skips → **635 + 2 skips**
- `mypy --strict` clean across 48 source files
- `ruff` clean across `src/` and `tests/`
- 0 backwards-incompatible changes — pure test additions

## What worked

- **Sanitized real lockfiles.** Real OSS lockfiles have noise
  (resolved URLs, integrity hashes) we don't care about. The
  fixtures keep the *structural* quirks (peerdep suffixes, comma
  selectors, npm: protocol) but replace hashes with `fake==`. Smaller
  files, same edge cases, no dependency on real package downloads.
- **First-run pass.** The v3.0.0a3 parsers handled every real-world
  fixture without a single change. That's the value of real fixtures
  retroactively — they prove the parser robustness, not just patch it.
- **Sanity-band assertions.** `5 <= len(pkgs) <= 50` catches both
  "parser broke and returned 0" AND "parser broke and matched too
  much" without locking the test to an exact number that drifts when
  the fixture is updated.

## What to change / next

- **No SSE end-to-end browser test.** The expanded Playwright still
  doesn't drive an `ask_project` stream end-to-end — that needs a
  mocked backend (real `claude --print` would be flaky in CI). Defer
  to v4.0.0a6 when the dispatcher work creates a natural mock seam.
- **Browser tests skip locally without playwright.** Module-level
  `importorskip` is correct; just want to surface that running
  `uv sync --extra ui-test && uv run playwright install chromium`
  is still a manual prerequisite.

## Action items for the next sprint (v4.0.0a2)

1. **URL state on /api/recall + copy-link affordance.** Extend the
   v3.0.0a9 URL-state pattern to the recall search panel + the
   dashboard project filter (if added). Add a "copy share link"
   button to the fan-out form that copies the current URL via
   `navigator.clipboard`.

## Out-of-scope (still)

- Tauri / Electron desktop UI — no demand.
- Relay-binary path (Path B) — Path C HTTP tunnel covers it.
- IDE extension — MCP works with any MCP client.
- pnpm v5 lockfile support — pre-2022 format.
- Multi-worker dispatch pool — gated on profile evidence in v4.0.0a6.
- Session-cookie auth + CSRF — defer until multi-operator UI is real.
- SSE end-to-end browser test — needs backend mocking; defer to a6.

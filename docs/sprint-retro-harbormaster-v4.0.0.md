# Sprint Retro — Harbormaster v4.0.0 GA

**Date:** 2026-05-09
**Theme:** v4.0 is the polish-and-harden release. v3 closed every loop;
v4 hardens the surface and fills in operational ergonomics. Single
monolithic alpha line (a1-a6), now GA.

## What landed

| Tag | SHA | Subject |
|-----|-----|---------|
| v4.0.0a1 | (per branch) | feat(tests): real-world lockfile fixtures + expanded Playwright |
| v4.0.0a2 | `b5d1a20` | feat(ui): URL state on /api/recall + copy-link affordance |
| v4.0.0a3 | `9412497` | feat(ui): graph pinch-zoom + drag-pan |
| v4.0.0a4 | `e8dfe80` | feat(ui): optimistic trajectory insert |
| v4.0.0a5 | (per branch) | feat(history): auto-reembed on drift detection |
| v4.0.0a6 | `e1d81a8` | feat(fleetq): multi-worker dispatcher pool |
| **v4.0.0** | _ship commit_ | drop alpha, GA retro |

## v4 capabilities — what changed user-facing

### Test coverage hardening

- **Real-world lockfile fixtures (a1).** pnpm v6 / v9 / yarn v1 / yarn
  berry snippets exercising peerDep suffixes, comma selectors,
  `npm:` protocol, `__metadata` block. The v3.0.0a3 parsers passed
  every test on first run.
- **Expanded Playwright smoke (a1).** Recall panel rendering,
  selectAll/None toggle, URL state on form interactions, project
  detail navigation, card chrome non-navigation guard.

### UI ergonomics

- **URL state on recall + copy-link (a2).** Recall search shareable
  via `recall_q=...&recall_project=...&recall_host=...`. Fan-out
  form has a `copy link` button that uses `navigator.clipboard`.
- **Graph pinch-zoom (a3).** Touch + wheel + mouse-drag for the
  Mermaid graph viewport. Pure JS, no library. `0.25× .. 4×` clamp
  + reset button.
- **Optimistic trajectory insert (a4).** `hm:trajectory:append` event
  prepends a synthetic Q&A entry instantly; reconciliation on next
  load. Cyan border + "● new" badge differentiates optimistic entries.

### Operational

- **Auto-reembed on drift (a5).** `[history] auto_reembed_on_drift = true`
  spawns a background thread on startup that walks every per-host
  store and reembeds any with detected drift. Cross-process state
  file + `/api/history/state` endpoint.
- **Multi-worker dispatcher pool (a6).** v3.0.0a5 single-worker
  promoted to opt-in `[fleetq] dispatcher_max_workers > 1` (bounded
  ThreadPoolExecutor). Stress test (50 concurrent dispatches, mixed
  valid + invalid) proves thread-safety before shipping.

## Real numbers (cumulative across v4.0)

- 6 PRs (one per phase) merged via `git merge --no-ff` (skip-PR-default)
- 7 v4.0 tags published (a1..a6 + GA)
- Test suite delta: 621 + 2 skips → **670 + 2 skips**
  - +49 unit tests across the alpha line
  - +2 integration stress tests
- `mypy --strict` clean across **49 source files** (was 48 at v3.0.0)
- `ruff` clean across `src/` and `tests/` throughout the line
- 0 backwards-incompatible changes — every v4 feature is opt-in via
  config or additive UI / event surface
- 9 CI jobs per push (unchanged from v3 GA)

## Architectural additions

- `harbormaster.history.auto_reembed.{ReembedState, run_auto_reembed,
  maybe_start_auto_reembed_thread, read_state}` — cross-process
  reembed runner
- `tests/fixtures/lockfiles/` — real-world parser regression suite
- `tests/integration/test_dispatcher_stress.py` — thread-safety
  stress test (50 concurrent dispatches)
- `BridgeRelay.dispatcher_max_workers` constructor kwarg + pool path
  in `_worker_loop`
- Dashboard / project_detail UI: graphZoom() Alpine factory,
  hm:trajectory:append handling + reconciliation, recall URL state
- `_partials/_ask_form_script.html`: append event dispatch alongside
  the v3.0.0a8 dirty event
- `_partials/delegate_form.html`: same append event dispatch
- `/api/history/state` endpoint
- New config:
  - `[history] auto_reembed_on_drift: bool = false`
  - `[fleetq] dispatcher_max_workers: int = 1`

## Release flow (proven, four-time successful: v2.0, v2.1, v3.0, v4.0)

```
1. Branch: feat/v<N>.<P>-<phase-name>
2. Implement, test (mypy strict + ruff + pytest); local pre-flight
3. Commit + push branch (backup, no PR)
4. git checkout main; git merge --no-ff feat/...
5. Bump __version__ on main
6. Write docs/sprint-retro-harbormaster-v<N>.<P>a<K>.md
7. Commit "ship: bump to <N>.<P>a<K> + sprint retro"
8. Tag v<N>.<P>a<K> and push tag (PyPI Trusted Publishing fires)
9. Verify on https://pypi.org/project/harbormaster-mcp/
10. Repeat for next phase
11. After last alpha → GA: bump to <N>.<P>.0, write GA retro, tag v<N>.<P>.0
```

## v5+ candidate phases (priority order from v4 retros)

1. Auto-reembed UI panel (consume /api/history/state)
2. Stress-test coverage for backend-invoking tools (fake-claude
   harness, wider thread-safety proof)
3. Per-tool thread-safety map (selective opt-in for the pool)
4. Cross-fade / writeback spinner for optimistic trajectory entries
5. Double-tap-to-reset / keyboard shortcuts on graph zoom
6. Auto-reembed exponential-backoff retry on transient failure
7. URL state on dashboard project filter (when filter UI added)

## Out-of-scope for v5 too (push to v6+)

- Tauri / Electron desktop UI wrapper — still no demand
- Relay-binary path (Path B) — Path C HTTP tunnel covers it
- Built-in IDE extension (VS Code / JetBrains)
- LLM extraction for remote hosts (heuristic only over SSH)
- Cross-model vector translation (use reembed)
- Session-cookie auth + CSRF (defer until multi-operator UI)
- pnpm v5 lockfile (pre-2022 format)
- Cross-process file locking on bridge / reembed state (single-writer)
- IE11 / pre-2018 clipboard fallback — modern browser only

## Already-decided (don't re-litigate)

- MIT license · PyPI namespace `harbormaster-mcp` · hatchling build
- Trusted Publishing on PyPI (production + TestPyPI)
- Backend abstraction = Protocol (since v2.0.0a3)
- Streaming via SSE locally; Pusher client events on Bridge
- All v4 features opt-in via config gates — zero breaking changes
  from v3
- UI stack stays no-build (Jinja + Tailwind + Alpine + HTMX +
  Mermaid via CDN)
- Skip-PR default — feature branches merged locally, no GitHub PR
  step (per user feedback 2026-05-09)
- Single-writer assumption on cross-process state files

# Sprint Retro — Harbormaster v5.0.0 GA

**Date:** 2026-05-09
**Theme:** v5.0 is the polish-and-extend release. v4 hardened; v5
filled the operational gaps and refined the rough edges. Single
monolithic alpha line (a1-a6), now GA.

## What landed

| Tag | SHA | Subject |
|-----|-----|---------|
| v5.0.0a1 | `310813e` | feat(history+ui): auto-reembed UI panel + retry |
| v5.0.0a2 | `7454135` | test(integration): backend-tools stress via fake-claude |
| v5.0.0a3 | `ab3c319` | feat(fleetq): per-tool thread-safety map |
| v5.0.0a4 | `ba13c88` | feat(ui): optimistic trajectory polish |
| v5.0.0a5 | `e558b76` | feat(ui): graph zoom UX polish |
| v5.0.0a6 | `adf39c8` | feat(ui): dashboard project filter + URL state |
| **v5.0.0** | _ship commit_ | drop alpha, GA retro |

## v5 capabilities — what changed user-facing

### Operational visibility

- **Auto-reembed UI panel (a1).** The `/api/history/state` endpoint
  added in v4.0.0a5 now has a UI. Phase badge + progress bar +
  current host + last-error all live; auto-polls 3s while running.
- **Auto-reembed retry (a1).** 1 + 3 retry × (1s/2s/4s) backoff on
  transient open / reembed failures. Permanent failures still
  surface the error after 4 attempts.

### Concurrency hardening

- **Backend-tools stress (a2).** `tests/fixtures/fake_claude.py`
  wired into the dispatcher stress; 50 concurrent ask_project
  dispatches verified safe.
- **Per-tool thread-safety map (a3).** `SAFE_FOR_PARALLEL` allowlist
  + operator deny list (`[fleetq] dispatcher_unsafe_tools`). Selective
  pool opt-in: known-safe tools fan out; unknown / deny-listed
  tools fall through to the worker.

### UI polish

- **Optimistic trajectory polish (a4).** 200ms cross-fade on
  optimistic→real reconciliation (in-place merge keeps DOM stable).
  Amber writeback spinner appears on optimistic entries older than 5s.
- **Graph zoom UX (a5).** Double-tap-to-reset on touch (300ms);
  desktop keyboard shortcuts (`+/-` zoom, arrows pan, Escape reset)
  with form-field guard.
- **Dashboard project filter (a6).** Substring filter across name +
  path + brief; URL state via `?filter=...` (default-omit, foreign
  param preservation).

## Real numbers (cumulative across v5.0)

- 6 PRs (one per phase) merged via `git merge --no-ff` (skip-PR-default)
- 7 v5.0 tags published (a1..a6 + GA)
- Test suite delta: 670 + 2 skips → **702 + 2 skips**
  - +30 unit tests across the alpha line
  - +2 backend-stress integration tests
- `mypy --strict` clean across **49 source files** (unchanged from v4)
- `ruff` clean across `src/` and `tests/` throughout the line
- 0 backwards-incompatible changes — every v5 feature is opt-in via
  config or additive UI / event surface
- 9 CI jobs per push (unchanged from v4)

## Architectural additions

- `harbormaster.fleetq.dispatcher.{SAFE_FOR_PARALLEL,
  is_tool_safe_for_parallel}` — per-tool routing decision
- `harbormaster.history.auto_reembed._RETRY_BACKOFF_SECONDS` —
  module-level backoff schedule (overridable in tests via
  monkeypatch)
- `BridgeRelay.dispatcher_unsafe_tools` constructor kwarg
- Dashboard `reembedPanel()`, `projectGrid()` Alpine factories
- project_detail's `trajectoryList`: in-place reconciliation,
  `init()/destroy()` 1s tick, `isStale()` helper, content-tuple `:key`
- graphZoom: `_lastTapTime` (double-tap), `onKeyDown(e)` (keyboard)
- `tests/integration/test_dispatcher_stress.py`: backend-tools
  coverage via fake-claude

## Release flow (proven, five-time successful: v2.0, v2.1, v3.0, v4.0, v5.0)

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

Three monolithic-alpha-line releases in a row (v3, v4, v5) confirm
the cadence works for both major-feature lines AND polish-and-extend
lines.

## v6+ candidate phases (priority order from v5 retros)

1. Manual "trigger reembed now" button (operator-initiated, beyond
   startup-only path)
2. Auto-reembed ETA estimation (rate signal once stabilized)
3. Streaming-chunks stress (when streaming path bottlenecks)
4. Stuck-writeback escalation tier (>30s → red error indicator)
5. Configurable stale threshold (operators with very slow networks)
6. Keyboard shortcut help popover (graph zoom + future shortcuts)
7. Sort/group controls on the dashboard (alpha sort, language grouping)
8. Full-text search inside CLAUDE.md / Serena memories (separate
   indexer)
9. CLI dispatcher-status command (introspect SAFE_FOR_PARALLEL +
   deny list at runtime)

## Out-of-scope for v6 too (push to v7+)

- Tauri / Electron desktop UI wrapper — still no demand
- Relay-binary path (Path B) — Path C HTTP tunnel covers it
- Built-in IDE extension (VS Code / JetBrains)
- LLM extraction for remote hosts (heuristic only over SSH)
- Cross-model vector translation (use reembed)
- Session-cookie auth + CSRF (defer until multi-operator UI)
- pnpm v5 lockfile (pre-2022 format)
- Cross-process file locking on bridge / reembed state (single-writer)
- IE11 / pre-2018 clipboard fallback — modern-browser-only is fine
- Config-driven safety allowlist — keep code-controlled by design

## Already-decided (don't re-litigate)

- MIT license · PyPI namespace `harbormaster-mcp` · hatchling build
- Trusted Publishing on PyPI (production + TestPyPI)
- Backend abstraction = Protocol (since v2.0.0a3)
- Streaming via SSE locally; Pusher client events on Bridge
- All v5 features opt-in via config gates — zero breaking changes
  from v4
- UI stack stays no-build (Jinja + Tailwind + Alpine + HTMX +
  Mermaid via CDN)
- Skip-PR default — feature branches merged locally, no GitHub PR
  step (per user feedback 2026-05-09)
- Single-writer assumption on cross-process state files
- SAFE_FOR_PARALLEL is code-controlled (not config-driven) — adding
  a tool to the allowlist requires a stress-test PR

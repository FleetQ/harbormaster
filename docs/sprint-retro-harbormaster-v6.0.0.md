# Sprint Retro — Harbormaster v6.0.0 GA

**Date:** 2026-05-09
**Theme:** v6.0 closes loops left from v5: operational visibility for
auto-reembed, escalation tier on optimistic entries, dashboard
organisation, keyboard help discoverability, streaming-path stress,
and a CLI introspection command. Single monolithic alpha line (a1-a6),
now GA.

## What landed

| Tag | SHA | Subject |
|-----|-----|---------|
| v6.0.0a1 | `6f3392f` | feat(history+ui): manual reembed trigger + ETA |
| v6.0.0a2 | `d78cee1` | feat(ui): optimistic escalation tier + threshold |
| v6.0.0a3 | `697000e` | feat(ui): dashboard sort + group controls |
| v6.0.0a4 | `1656754` | feat(ui): keyboard shortcut help popover |
| v6.0.0a5 | `56673a1` | test(integration): streaming-chunks dispatcher stress |
| v6.0.0a6 | (per branch) | feat(cli): harbormaster-mcp dispatcher status |
| **v6.0.0** | _ship commit_ | drop alpha, GA retro |

## v6 capabilities — what changed user-facing

### Operations

- **Manual reembed (a1).** `POST /api/history/reembed` + dashboard
  "run now" button. Idempotent under double-click. ETA estimation
  in the panel based on rate signal.
- **Escalation tier (a2).** Three-tier optimistic visual: fresh /
  stale / stuck. Configurable threshold via `[history] optimistic_stale_seconds`.
- **`harbormaster-mcp dispatcher status` (a6).** SAFE_FOR_PARALLEL
  + deny list + effective set printed at runtime. Mirrors the v2.0.1
  `plugins list` pattern.

### UI organisation

- **Sort + group (a3).** Sort dropdown (recent / alpha / language).
  Group toggle (flat / by language). Server-side `_detect_language`
  derives Python / JS / PHP / Rust / Go / unknown.
- **Keyboard help popover (a4).** `?` toggles a popover listing every
  shortcut. Single source of truth (shortcut array); `<kbd>` styled
  list with click-away dismissal.

### Concurrency hardening

- **Streaming stress (a5).** 50 concurrent agent.requests, each
  yielding 5 chunks via the dispatcher pool. Per-request chunk
  ordering preserved. Mid-stream stop() shuts down cleanly.

## Real numbers (cumulative across v6.0)

- 6 PRs (one per phase) merged via `git merge --no-ff` (skip-PR-default)
- 7 v6.0 tags published (a1..a6 + GA)
- Test suite delta: 702 + 2 skips → **737 + 2 skips**
  - +33 unit tests across the alpha line
  - +2 streaming-stress integration tests
- `mypy --strict` clean across **50 source files** (was 49 at v5.0;
  +1: dispatcher_cli.py)
- `ruff` clean across `src/` and `tests/` throughout the line
- 0 backwards-incompatible changes — every v6 feature is opt-in via
  config or additive UI / CLI / state field
- 9 CI jobs per push (unchanged from v5.0)

## Architectural additions

- `harbormaster.history.auto_reembed.trigger_manual_reembed`
- `[history] optimistic_stale_seconds` config (Pydantic-validated 1..600)
- `ProjectInfo.language` field + `_detect_language()` helper
- `harbormaster.dispatcher_cli` module (new CLI subcommand)
- Dashboard `helpPopover()` Alpine factory + shortcuts array
- Dashboard `projectGrid` `_sortProjects` + `groupedProjects` +
  URL state for sort/group keys
- `tests/integration/test_dispatcher_stress.py` streaming + mid-stream
  shutdown coverage

## Release flow (proven, six-time successful: v2.0, v2.1, v3.0, v4.0, v5.0, v6.0)

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
11. After last alpha → GA: bump to <N>.<P>.0, write GA retro,
    tag v<N>.<P>.0
```

Six successful monolithic alpha lines confirms the cadence works
across both major-feature and polish-and-extend releases.

## v7+ candidate phases (priority order from v6 retros)

1. Cancel-running-reembed button
2. Reembed run history (state.json overwrites, would need a log)
3. Per-host optimistic stale thresholds
4. Language badge on dashboard cards (flat-mode discoverability)
5. ManifestCache for /api/projects (defer until profiled)
6. Auto-derived keyboard shortcuts array (single source of truth)
7. Page-aware help popover filtering (when popover moves to base.html)
8. Streaming chunk-timing assertion (latency regression guard)
9. Memory-pressure stress (10K+ chunks)
10. `--json` output mode for `dispatcher status` CLI
11. Full-text search inside CLAUDE.md / Serena memories (separate
    indexer, longstanding)

## Out-of-scope for v7 too (push to v8+)

- Tauri / Electron desktop UI wrapper — still no demand
- Relay-binary path (Path B) — Path C HTTP tunnel covers it
- Built-in IDE extension (VS Code / JetBrains)
- LLM extraction for remote hosts (heuristic only over SSH)
- Cross-model vector translation (use reembed)
- Session-cookie auth + CSRF (until multi-operator UI)
- pnpm v5 lockfile (pre-2022 format)
- Cross-process file locking on bridge / reembed state (single-writer)
- IE11 / pre-2018 clipboard fallback
- Config-driven SAFE_FOR_PARALLEL — keep code-controlled by design

## Already-decided (don't re-litigate)

- MIT license · PyPI namespace `harbormaster-mcp` · hatchling build
- Trusted Publishing on PyPI (production + TestPyPI)
- Backend abstraction = Protocol (since v2.0.0a3)
- Streaming via SSE locally; Pusher client events on Bridge
- All v6 features opt-in via config gates — zero breaking changes
  from v5
- UI stack stays no-build (Jinja + Tailwind + Alpine + HTMX +
  Mermaid via CDN)
- Skip-PR default — feature branches merged locally, no GitHub PR
  step (per user feedback 2026-05-09)
- Single-writer assumption on cross-process state files
- SAFE_FOR_PARALLEL is code-controlled (allowlist requires PR with
  stress-test); operator deny list is config (per-deployment override)

# Harbormaster v6 Roadmap

**Drafted:** 2026-05-09 (after v5.0.0 GA shipped same day)

v5 was polish-and-extend. v6 continues the pattern: small operational
improvements, surface introspection, and one-more-iteration on the
auto-reembed / dispatcher / optimistic flows that v3-v5 already
established.

Single monolithic v6.0 line — every phase ships as `v6.0.0a1` …
`v6.0.0a6`, then `v6.0.0` GA.

## Out-of-scope for v6 (defer to v7+)

Carried forward from v5 retros + reaffirmed:

- Tauri / Electron desktop UI wrapper (still no demand)
- Relay-binary path (Path B) (Path C HTTP tunnel covers it)
- Built-in IDE extension (VS Code / JetBrains)
- Session-cookie auth + CSRF — defer until multi-operator UI is real
- LLM-based triple extraction for remote hosts (heuristic only over SSH)
- Cross-model vector translation (use reembed instead)
- pnpm v5 lockfile support (pre-2022 format)
- Cross-process file locking on bridge / reembed state (single-writer)
- IE11 / pre-2018 clipboard fallback
- Config-driven SAFE_FOR_PARALLEL — keep code-controlled by design
- Full-text search inside CLAUDE.md / Serena memories — separate
  indexer scope, defer to v7

## Phases

### Phase 1 — Manual reembed trigger + ETA estimation (`v6.0.0a1`)

v4.0.0a5 auto-reembed runs on startup only. Operators who bumped the
embedding model mid-day can't trigger a re-run without restarting
the MCP process.

- New `POST /api/history/reembed` endpoint — spawns the same background
  thread as the startup-time auto-reembed, but only when no run is
  already in progress (returns 409 Conflict if state.phase=="running")
- UI button in `reembedPanel` calls the endpoint, surfaces the new
  state immediately
- ETA estimation: when state.phase=="running", compute
  `(now - started_at) / max(processed, 1) * (total - processed)`;
  surfaced in the panel as `~Xs remaining` once `processed >= 1`

### Phase 2 — Optimistic escalation tier + configurable threshold (`v6.0.0a2`)

v4.0.0a4 + v5.0.0a4 left optimistic entries with a single threshold
(5s) and a single visual tier (amber spinner). Two refinements:

- New `[history] optimistic_stale_seconds: int = 5` config — operators
  with slow networks can bump
- Two visual tiers in `trajectoryList`:
  - Age 0..stale_seconds → cyan "● new" badge (unchanged)
  - Age stale_seconds..(stale_seconds × 6) → amber spinner (today)
  - Age > stale_seconds × 6 → red "writeback stuck?" indicator

  Default: 0..5s → 5..30s → >30s. Configurable.
- Plumb the threshold through the `auth_token`-style template ctx so
  the JS reads it from a meta tag (avoids hardcoding in the partial)

### Phase 3 — Dashboard sort + group controls (`v6.0.0a3`)

The v5.0.0a6 filter only narrows. Operators with 50+ projects also
want to *organise* the visible set.

- Sort dropdown above the grid: `last_commit (desc)` / `alpha` /
  `language` (lockfile-derived)
- Group toggle: `flat` / `by language` — when enabled, projects
  cluster under per-language headings (Python / JS / Rust / etc.)
- URL state alongside `filter`: `?sort=alpha&group=language`

### Phase 4 — Keyboard shortcut help popover (`v6.0.0a4`)

v5.0.0a5 added graph zoom shortcuts; nobody knows about them. Surface
them via a help affordance.

- `?` key (in the same form-field-guarded handler from v5.0.0a5)
  opens a fixed-position popover listing all shortcuts
- Single source of truth: a JS array of `{ key, action, scope }`
  rendered into both the popover and (future) the discoverability hover
- `Escape` dismisses the popover (same as it dismisses graph zoom reset)
- Help icon in the dashboard header opens the same popover for
  pointer users

### Phase 5 — Streaming-chunks dispatcher stress (`v6.0.0a5`)

v4.0.0a6 + v5.0.0a2 stress proved the dispatcher safe under
concurrency for non-streaming responses. The v1.0.0a14 streaming
path (per-chunk SSE on `/mcp/{server}`) wasn't covered.

- New stress test in `tests/integration/test_dispatcher_stress.py`
  exercising a chunk-yielding handler under 16-worker fan-out
- Verifies: each request's chunks are not interleaved with another
  request's chunks (per-request ordering preserved)
- Verifies: pool shutdown mid-stream doesn't leave half-emitted chunks
  on the wire (cleanup semantics match the single-worker path)

### Phase 6 — `harbormaster-mcp dispatcher status` CLI (`v6.0.0a6`)

v5.0.0a3 introduced `SAFE_FOR_PARALLEL` + operator deny list.
Operators can `cat` the config to see the deny list, but the
allowlist requires reading the source. Surface both at runtime.

- New `harbormaster-mcp dispatcher status` subcommand (mirrors
  the `plugins list` pattern from v2.0.1)
- Prints:
  - `SAFE_FOR_PARALLEL` set (sorted)
  - Configured `dispatcher_max_workers`
  - Configured `dispatcher_unsafe_tools` deny list
  - Effective allowlist (SAFE_FOR_PARALLEL minus deny list)

### v6.0.0 GA

Drop alpha. Write `docs/sprint-retro-harbormaster-v6.0.0.md`. Bump
README status. No new code in the GA tag — just the version bump
(mirroring v1-v5 GA pattern).

## Already-decided (don't re-litigate)

- Same release flow as v1-v5: branch per phase, **local merge** (no
  PR), bump version, retro, tag, push, PyPI auto-publishes via
  Trusted Publishing
- All new behavior is opt-in via config gates (matching v1-v5 discipline)
- No breaking changes to the v5 tool surface; new tools / new args only
- mypy --strict + ruff stay non-negotiable
- UI stack stays no-build (Jinja + Tailwind + Alpine + HTMX +
  Mermaid via CDN)

## Order rationale

- a1 first: closes the v5.0.0a1 retro gap (trigger button) and gives
  an early UI affordance for the operational endpoint we already have
- a2 builds on the v5.0.0a4 visual-tier work fresh in mind
- a3-a4 are pure UI; a3's filter+sort+group convergence is the natural
  point to also surface the "?" help (a4)
- a5 (streaming stress) is the last concurrency item we haven't proven
- a6 closes the v5.0.0a3 retro action ("CLI dispatcher-status command")

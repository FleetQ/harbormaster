# Harbormaster v5 Roadmap

**Drafted:** 2026-05-09 (after v4.0.0 GA shipped same day)

v4 hardened the surface and filled in operational ergonomics. v5 is
the polish-and-extend release: UI panels for the operational
endpoints v4 added, broader thread-safety proof, selective opt-in
controls, and small UX refinements that didn't fit a major bump.

Single monolithic v5.0 line — every phase ships as `v5.0.0a1` …
`v5.0.0a6`, then `v5.0.0` GA.

## Out-of-scope for v5 (defer to v6+)

Carried forward from v4 retros, plus reaffirmed deferrals:

- Tauri / Electron desktop UI wrapper (still no demand)
- Relay-binary path (Path B) (Path C HTTP tunnel covers it)
- Built-in IDE extension (VS Code / JetBrains) — MCP works with any
  MCP client
- Session-cookie auth + CSRF — defer until multi-operator UI is real
- LLM-based triple extraction for remote hosts (heuristic only over SSH)
- Cross-model vector translation (use reembed instead)
- pnpm v5 lockfile support (pre-2022 format)
- Cross-process file locking on bridge / reembed state (single-writer)
- IE11 / pre-2018 clipboard fallback — modern-browser-only is fine

## Phases

### Phase 1 — Auto-reembed UI panel + exponential-backoff retry (`v5.0.0a1`)

Two related improvements to the v4.0.0a5 auto-reembed subsystem.

**UI panel** — consume the `/api/history/state` endpoint that v4 added
but didn't render anywhere. Dashboard gets a panel showing:
- Phase badge (idle / running / done / failed)
- Progress bar (`processed / total`)
- Current host being processed (during running)
- Last error (if failed)
- Started / finished timestamps

**Exponential-backoff retry** — `_reembed_one_host` currently fails
on first transient SSH / sqlite-busy error. v5.0.0a1 adds 3 retries
at 1s / 2s / 4s before giving up on a host. Permanent failures
(e.g. corrupt db) still surface to the runner's `error` field.

### Phase 2 — Stress test for backend-invoking tools (`v5.0.0a2`)

`tests/integration/test_dispatcher_stress.py` covers read-only tools
(`list_projects`, `list_hosts`, `project_graph`). v5.0.0a2 wires
the existing `tests/fixtures/fake_claude.py` harness into the
dispatcher to stress `ask_project` + `delegate_task`. Verifies:

- Concurrent backend invocations don't share / corrupt subprocess state
- Streaming chunk paths aren't interleaved across requests
- Cleanup runs (subprocess close, store close) under concurrency

If anything turns up, ship it as a regression guard; if green,
operators can opt into `dispatcher_max_workers > 1` with confidence
on the full tool surface.

### Phase 3 — Per-tool thread-safety map (`v5.0.0a3`)

Today the dispatcher pool is all-or-nothing — either every tool
runs through the pool or none do. Some tools may be safe to
parallelise even if others aren't (e.g. read-only `list_projects`
vs. write-side `delegate_task`).

- New `harbormaster.fleetq.dispatcher.SAFE_FOR_PARALLEL: frozenset[str]`
  classification (default: all read-only tools)
- Dispatcher inspects the requested tool name; unsafe tools are
  routed back to the worker thread (single-threaded), safe tools
  go through the pool
- Configurable override via `[fleetq] dispatcher_unsafe_tools: list[str]`
  (operator can mark additional tools unsafe)

### Phase 4 — Optimistic trajectory polish (`v5.0.0a4`)

The v4.0.0a4 optimistic entries appear instantly but reconcile
abruptly — the cyan border just disappears when the server entry
takes over. Two refinements:

- Alpine `x-transition` cross-fade: 200ms transition when
  reconciling optimistic → real
- "Writing back…" spinner on optimistic entries older than 5s
  (signals to the operator that something might be slow / wrong)

### Phase 5 — Graph zoom UX polish (`v5.0.0a5`)

Two missing input modalities for the v4.0.0a3 graph viewport:

- Double-tap-to-reset on touch (mobile equivalent of the desktop
  reset button)
- Keyboard shortcuts on desktop:
  - `+` / `=` zoom in, `-` zoom out (centred on viewport)
  - Arrow keys pan
  - `Escape` resets

### Phase 6 — Dashboard project filter + URL state (`v5.0.0a6`)

Today the dashboard project grid renders all discovered projects
without any filter. v5.0.0a6 adds:

- New text input above the grid, filters cards by
  `name | path | brief` substring match
- Filter state encoded in URL as `?filter=...` (v3.0.0a9 pattern)
- Auto-applies on mount when URL has `filter=`
- "Showing X of Y" counter when active

### v5.0.0 GA

Drop alpha. Write `docs/sprint-retro-harbormaster-v5.0.0.md`. Bump
README status. No new code in the GA tag — just the version bump
(mirroring v1/v2/v3/v4 GA pattern).

## Already-decided (don't re-litigate)

- Same release flow as v1-v4: branch per phase, **local merge** (no
  PR), bump version, retro, tag, push, PyPI auto-publishes via
  Trusted Publishing
- All new behavior is opt-in via config gates (matching v1-v4 discipline)
- No breaking changes to the v4 tool surface; new tools / new args only
- mypy --strict + ruff stay non-negotiable
- UI stack stays no-build (Jinja + Tailwind + Alpine + HTMX +
  Mermaid via CDN)

## Order rationale

- a1 first: auto-reembed UI + retry close the loop on v4.0.0a5 — both
  parts need the same subsystem visible
- a2-a3 are concurrency hardening; a2 (stress) gates a3 (selective
  opt-in) — prove the safety map first, then ship the map
- a4-a5 are pure UI polish; can ship in any order
- a6 last because the filter UI reuses the v3.0.0a9 URL state
  pattern that's been three phases away from anyone's working memory

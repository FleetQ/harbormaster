# Harbormaster v4 Roadmap

**Drafted:** 2026-05-09 (after v3.0.0 GA shipped same day)

v3 closed every loop the v2 retros flagged. v4 is a polish-and-harden
release: real-world test coverage, URL state polish across more
surfaces, mobile-friendly graph zoom, optimistic UI updates, an
operator-friendly auto-reembed path, and multi-worker dispatch
gated on a thread-safety proof.

Single monolithic v4.0 line — every phase ships as `v4.0.0a1` …
`v4.0.0a6`, then `v4.0.0` GA.

## Out-of-scope for v4 (defer to v5+)

Carried forward from v3 retros:

- Tauri / Electron desktop UI wrapper (still no demand)
- Relay-binary path (Path B) (Path C HTTP tunnel covers it)
- Built-in IDE extension (VS Code / JetBrains) — MCP works with any
  MCP client
- Session-cookie auth + CSRF — defer until multi-operator UI is real
- LLM-based triple extraction for remote hosts (heuristic only over SSH)
- Cross-model vector translation (use reembed instead)
- pnpm v5 lockfile support (pre-2022 format)
- Cross-process file locking on bridge state (single-writer in practice)

## Phases

### Phase 1 — Real-world lockfile fixtures + expanded Playwright (`v4.0.0a1`)

Two test-coverage gaps from v3 retros, bundled.

- Vendor lockfiles from popular OSS projects (React, Vue, Next.js,
  Astro, SvelteKit) into `tests/fixtures/lockfiles/`
- Assert v3.0.0a3 pnpm + yarn parsers extract sane package sets
  against those real-world quirks
- Expand Playwright smoke (`tests/ui/test_browser_*.py`):
  - SSE stream end-to-end with a mocked ask_project tool
  - Trajectory refresh round-trip after ask completion
  - Fan-out submit + result rendering

### Phase 2 — URL state on `/api/recall` + copy-link affordance (`v4.0.0a2`)

Extends the v3.0.0a9 URL-state pattern to additional surfaces.

- Recall search inline (`dashboard.html` recall panel): encode
  `q`, `project`, `top_k`, `min_similarity` into URL params
- Dashboard project filter (when added — currently no filter UI;
  this phase adds one if absent + URL-states it)
- Fan-out form: a "copy share link" button next to the Run button
  that copies the current URL to clipboard via `navigator.clipboard`
- Same `replaceState` pattern; same default-omit serialization

### Phase 3 — Graph pinch-zoom for mobile (`v4.0.0a3`)

Wrap the Mermaid `<pre>` / SVG in a transform container with a
small pinch-zoom + drag-pan handler.

- Pure JS (no library); CSS `transform: scale() translate()`
- Pinch via touchstart/touchmove on iOS Safari + Android Chrome
- Mouse-wheel zoom on desktop (preventDefault to avoid page scroll
  while hovering the graph)
- Reset button to return to scale=1 / translate=0
- Defer for non-graph elements; only the graph viewport has zoom

### Phase 4 — Optimistic trajectory insert (`v4.0.0a4`)

The v3.0.0a8 cross-section refresh fires a window event that
triggers a `/api/trajectories` reload. Round-trip is fast but
visible. Phase 4 prepends the just-streamed result client-side.

- `askForm()` / `delegateForm()` build a synthetic Q&A entry on
  stream completion using `{ project, question, answer:
  this.streamText, timestamp_s: Date.now()/1000 }`
- Dispatch a new event `hm:trajectory:append` carrying the entry
- Trajectory section listens for `:append` AND `:dirty` — append
  is fast (no fetch), dirty triggers an authoritative reload as
  a background reconciliation
- On the next page load / reload, server is source of truth; the
  optimistic entry would be replaced or reconciled away

### Phase 5 — Auto-reembed on drift detection (`v4.0.0a5`)

`QAStore.open()` already detects model drift and logs a warning.
Phase 5 adds an opt-in path that triggers the reembed CLI flow
in-process so operators don't have to remember to run it manually.

- New `[history] auto_reembed_on_drift: bool = false` (default
  off — operator decision is the v3 default; v4 makes auto a
  per-deployment choice)
- On detected drift: spawn the reembed loop in a background
  thread via the existing `harbormaster.history.cli` flow
- Status surfaces in `/api/bridge/status`-style endpoint:
  `/api/history/state` reporting in-progress / done / failed
- Tests: drift detection triggers reembed; reembed completes;
  status endpoint reports correct phase

### Phase 6 — Multi-worker dispatcher pool (`v4.0.0a6`)

v3.0.0a5 shipped a single-worker dispatcher because MCP tool
state wasn't proven thread-safe. v4 phase 6 ships:

1. **Profile + prove**: write a stress test that runs 50 concurrent
   recall_qa / ask_project / project_status calls through the
   in-process tool registry, asserting no deadlocks, no data
   corruption, no exception leaks
2. **Pool**: if (and only if) the stress test passes, replace the
   single-worker `_worker_loop` with a bounded `ThreadPoolExecutor`
   sized by new `[bridge] dispatcher_max_workers: int = 1` config
   (default 1 = behaviour-preserving)
3. **Operator opt-in**: documented in operator-guide.md with
   guidance on when bumping the pool size pays off

If the stress test surfaces a thread-safety issue, the phase ships
the test (as a regression guard) but defers the pool change.

### v4.0.0 GA

Drop alpha. Write `docs/sprint-retro-harbormaster-v4.0.0.md`. Bump
README status. No new code in the GA tag — just the version bump
(mirroring v1/v2/v3 GA pattern).

## Already-decided (don't re-litigate)

- Same release flow as v1/v2/v3: branch per phase, **local merge**
  (no PR — per user feedback 2026-05-09), bump version, retro,
  tag, push, PyPI auto-publishes via Trusted Publishing
- All new behavior is opt-in via config gates (matching v1/v2/v3
  discipline)
- No breaking changes to the v3 tool surface; new tools / new args only
- mypy --strict + ruff stay non-negotiable
- UI stack stays no-build (Jinja + Tailwind + Alpine + HTMX +
  Mermaid via CDN)
- Skip-PR default — feature branches merged locally, no GitHub PR
  step (per user feedback)

## Order rationale

- a1 first: test coverage hardens the surface BEFORE we layer
  more on top
- a2-a4 are pure UI polish; can ship in any order, but a2 (URL
  state extension) builds on the v3.0.0a9 mental model freshest
  in mind
- a5 (auto-reembed) is operational hygiene — useful even if a6 doesn't ship
- a6 last because it depends on the stress-test infrastructure
  that lands cleanly in a1

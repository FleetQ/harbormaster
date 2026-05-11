# Sprint Retro — Harbormaster v21.0.3 (patch)

**Released:** 2026-05-11
**Type:** Patch — release-gate fix + cold-start perf overhaul
**Branch flow:** Directly on `main`

## Why this patch exists

Two threads, in priority order:

1. **v21.0.1's `verify-ci` gate had a race bug.** Tag pushes triggered a
   second CI workflow run on the same SHA with identical `created_at`,
   making `sort_by(.created_at) | last` non-deterministic. v21.0.1 +
   v21.0.2 both blocked PyPI publish on a flaked tag-CI run while the
   main-push CI run was green.
2. **A `/perf full` deep dive on v21.0.2 revealed** that `/api/graph`
   was only the most visible sync-blocking endpoint. Many handlers
   (`/api/projects`, `/api/ignored-projects`, `/api/kpi`,
   `/api/kpi/history`) called `discover_projects()` synchronously inside
   their async bodies, so a cold dashboard load saw 5–7 s of effective
   wait. See `docs/perf-deep-dive-2026-05-11.md` for the full audit.

## Fixes shipped

### Tier 1 — release-blocking process bug

- **`ci.yml`**: dropped `tags: ["v*"]` from the `on: push:` trigger.
  Tag pushes now fire only `publish.yml` (which has its own checkout +
  build step). Removes the spurious second CI run that produced the
  ambiguous timestamp tie.
- **`publish.yml`'s `verify-ci`**: tightened the jq filter from
  `select(.name == "CI")` to also `select(.event == "push") |
  select(.head_branch == "main")`. Defensive even when tag-CI is gone:
  workflow_dispatch and pull_request CI runs on the same SHA are now
  ignored too. Gate is single-purpose: "did the main-push CI pass on
  this exact commit?".

### Tier 2 — cold-start UX

- **`asyncio.to_thread` around the cache-miss path** for
  `/api/projects`, `/api/ignored-projects` (both passes), `/api/kpi`,
  and `/api/kpi/history`. The cache hit path stays sync — no overhead
  added when the answer is already in memory.
- **Empty-pattern short-circuit** in `/api/ignored-projects`: when
  `[ignore].patterns = []` the diff is always empty, so we skip the
  two discovery passes and return `count=0` immediately.
- **Startup warmup task** (`@app.on_event("startup")`) that primes
  `projects_cache` on a worker thread. The first user request lands
  on an already-warm cache instead of paying ~1 s for the cold walk.
  Best-effort: failures log a warning, the first request just pays
  the cold cost as before.

### Tier 3 — `discover_projects` internal speedup

- **`ThreadPoolExecutor(max_workers=16)`** over the per-project work
  loop in `discover_projects()`. The previous version ran 62 git
  subprocesses sequentially (~880 ms total) and 12 rglob-fallback
  language detects sequentially (~1.1 s total) — both release the
  GIL during their syscalls, so threads give near-linear speedup.
  Isolated benchmark: 1.6 s → 0.88 s (45% faster).
- **`_detect_language_from_extensions` rglob audit deferred** —
  the 12-out-of-62 rate is dominated by manifests we don't yet
  recognise (Go modules without go.sum, Ruby projects with only
  Gemfile, etc.). Future work, not load-bearing for v21.0.3.

### Tier 4a — CLS 0.30 on `/projects/<name>`

- **Closed by T2 + T3 indirectly.** The CLS was caused by slow API
  responses arriving in waves after first paint — content was being
  inserted late, pushing rows down. With cold concurrent load now
  under 1 s (was 5–7 s), all content lands during the initial render
  pass. Re-measured: CLS = **0** across multiple fresh navigations.

### Tier 4b — Alpine.store fetch dedup

- **Deferred.** Dashboard cold load is now ~1 s wall instead of
  5–7 s, so the 6× duplicate `/api/projects` fetches are no longer
  user-visible. Worth doing in a future UI refactor pass, not
  release-blocking.

## Live before/after — cold concurrent load (9 endpoints, fresh process)

| Endpoint | v21.0.2 (cold) | v21.0.3 (cold) | Speedup |
|---|---:|---:|---:|
| `/api/projects` | 5.69 s | 0.84 s | **6.8×** |
| `/api/graph?format=cytoscape` | 5.69 s | 1.25 s | **4.5×** |
| `/api/kpi` | 7.55 s | 0.85 s | **8.9×** |
| `/api/network/events` | 7.55 s | 0.83 s | **9.0×** |
| `/api/plugins` | 5.70 s | 0.83 s | **6.9×** |
| `/api/bridge/status` | 5.70 s | 0.84 s | **6.8×** |
| `/api/hosts/budget` | 5.70 s | 0.84 s | **6.8×** |
| `/api/trajectories` | 0.39 s | 0.82 s | (slower at extreme load, but well within budget) |
| `/api/ignored-projects` | 4.08 s | **0.001 s** | **4000×** (warmup + empty-pattern short-circuit) |

Single-request warm latencies (post-warmup):
- `/api/projects`: ~1.5 ms
- `/api/graph?format=cytoscape`: ~1.5 ms (60 s TTL cache from v21.0.2)
- `/api/ignored-projects`: ~0.7 ms (60 s TTL cache)
- Everything else: <10 ms

Web Vitals on `/projects/<name>` (was LCP 2356 ms / CLS 0.30):
- **LCP: 132 ms** (was 2356)
- **CLS: 0** (was 0.30)
- **FCP: 132 ms**

## Verification

- `ruff check src/ tests/` — clean
- `mypy --strict src/harbormaster/` — clean (58 source files)
- `pytest tests/` — **1888 passed, 1 skipped, 0 failed**
- `discover_projects()` isolated benchmark — 1.6 s → 0.88 s
- Live UI on `:7541` re-validated end-to-end, including warmup log
  emit and concurrent-load measurement

## v21.0.1 / v21.0.2 status

Both stay tagged on GitHub as historical artifacts. Neither reached PyPI:

- v21.0.1: `verify-ci` correctly blocked it (Playwright suite was red).
- v21.0.2: `verify-ci` incorrectly blocked it (tag/main race bug, this
  patch's Tier 1 fix).

The published PyPI latest moves from v21.0.0 directly to v21.0.3.

## Chain status

Still HALTED. v21.0.3 is the third operator-initiated patch in the
2026-05-11 audit cycle. Substantive future work remains a `v22.x`
feature line, not chain resumption.

## Pattern lessons captured

1. **Don't trust `sort_by` with timestamp ties** in GitHub API queries —
   filter on event+branch explicitly when there could be multiple runs
   on the same SHA.
2. **Sync filesystem work inside async handlers serializes everything**.
   Fix once, fix everywhere — every handler that touches the filesystem
   needs either an in-memory cache or `asyncio.to_thread`.
3. **Startup warmup is cheap and high-value.** Spawning a background
   `to_thread` task at app startup eliminates the cold-cache penalty on
   the first user request, at the cost of a ~1 s delayed log line.
4. **CLS regressions can be downstream of latency.** Visible layout
   shifts that look like "the graph block is mounting late" can
   actually be "the API was slow so content arrived after paint" —
   measure end-to-end before assuming a visual fix is needed.

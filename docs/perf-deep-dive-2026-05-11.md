# Harbormaster — Deep Perf Dive (post-v21.0.2)

**Date:** 2026-05-11
**Subject:** v21.0.2 source tree (`harbormaster-ui` on `:7541`, 62 projects discovered, 0 ignore patterns)
**Reviewer:** Claude Opus 4.7 via Chrome MCP + cProfile of `discover_projects`
**Status of v21.0.2 on PyPI:** NOT published — `verify-ci` gate misfired (see end of doc)

---

## TL;DR

`/api/graph` was the **most visible** sync-blocking endpoint and v21.0.2's thread+TTL fix works. But **many other endpoints share the same root cause**: synchronous `discover_projects()` (~1.6 s) called directly inside async handlers. Until that broader pattern is fixed, the dashboard cold load still serializes ~5–7 s.

Also surfaced:
- **`/projects/<name>` has CLS 0.30** — layout shifts visibly during initial load.
- **`verify-ci` gate has a tag/main race** — picked the wrong CI run; v21.0.2 was not published.

---

## Re-baseline numbers (cold UI, 62 projects, no concurrent traffic)

| Endpoint | Solo curl (cold) | Solo curl (warm) | Cache present? |
|---|---:|---:|:-:|
| `/api/graph?format=cytoscape` | 2.33 s | 0.001 s | ✅ v21.0.2 TTL+thread |
| `/api/projects` | 1.73 s | 0.001 s (after 1 build) | ✅ `ProjectsCache` once warm |
| `/api/ignored-projects` | 4.08 s | 0.001 s | ⚠️ TTL cache, but **cold = 2× discover** |
| `/api/kpi` | 0.34 s | 0.003 s | partial |
| `/api/network/events?limit=10` | 1.7 ms | 0.9 ms | n/a |
| `/api/plugins` | 7.8 ms | 2.1 ms | n/a |
| `/api/bridge/status` | 7.4 ms | 0.8 ms | n/a |
| `/api/trajectories?limit=20` | 3.8 ms | 2.9 ms | n/a |
| `/api/hosts/budget` | 1.0 ms | 0.7 ms | n/a |

## Cold parallel load (9 endpoints fired together, fresh process)

```
/api/trajectories?limit=20:    0.388 s
/api/ignored-projects:         4.078 s
/api/projects:                 5.690 s
/api/graph?format=cytoscape:   5.691 s   ← in a thread, but still queued
/api/plugins:                  5.699 s
/api/hosts/budget:             5.699 s
/api/bridge/status:            5.703 s
/api/kpi:                      7.551 s
/api/network/events?limit=10:  7.552 s
```

**Reading:** `/api/ignored-projects` blocks the event loop for ~4 s doing two `discover_projects()` passes back-to-back. Everything else queues. `/api/kpi` then blocks for another ~3 s because it _also_ calls `discover_projects()` synchronously through the same `projects_cache` interface.

The `asyncio.to_thread` we added to `/api/graph` is correct, but it can't help while other sibling handlers are still blocking the loop.

---

## Root cause profile — `discover_projects()`

cProfile of one call (62 projects, no ignore patterns):

```
1.244 s  _detect_language               (62 calls, 20 ms each)
  1.109 s  _detect_language_from_extensions (12 calls, 92 ms each — pathlib.rglob fallback)
0.881 s  _git_last_commit              (62 sequential subprocess.run('git log ...') calls)
  0.730 s  select.poll                  (waiting for git subprocess output)
0.564 s  pathlib.Path.rglob            (71 533 calls)
0.131 s  graph.parser.parse_project    (per-project manifest parse)

Total: ~2.15 s wall (single thread, no parallelism)
```

Hot paths to fix:

1. **`_git_last_commit` runs sequentially** — 62 × ~14 ms subprocess spawns.
   `asyncio.gather` or `concurrent.futures.ThreadPoolExecutor(max_workers=16)`
   parallelises trivially → ~14 ms × ceil(62/16) ≈ 60 ms instead of 880 ms.
2. **`_detect_language_from_extensions` does pathlib.rglob fallback per project.**
   For projects that already have a manifest (pyproject.toml, package.json, etc.)
   the manifest-based detection runs first and SHOULD make the rglob fallback
   unnecessary. Check whether the fallback is firing when it should not — 12
   calls out of 62 is suspicious (the projects without a clear manifest).
3. **`discover_projects()` has no result cache.** `ProjectsCache` caches the
   _output_ of `/api/projects`, but the underlying `discover_projects()` call
   re-runs the full 1.6 s scan on every cache miss. A startup warmup task
   plus an mtime-keyed result cache would make cold-start cost amortised
   to ~0 for the normal operator session.

---

## CLS 0.30 on `/projects/<name>` — fail

| Surface | LCP | CLS | Verdict |
|---|---:|---:|---|
| `/` dashboard | 448 ms cold, 348 ms warm | 0 | ✅ Good |
| `/projects/<name>` | **2356 ms** | **0.303** | ❌ FAIL |
| `/tools/fan-out` | 2172 ms | 0 | ⚠️ Mediocre |
| `/network` | 360 ms | 0 | ✅ Good |

CLS 0.30 is over 3× the FAIL threshold (>0.25 = Poor). The project_detail
page has elements whose layout shifts after initial paint — likely:

- Mermaid / Cytoscape graph block mounting late and pushing content down
- Memory editor or trajectory list rendering rows asynchronously
- Image / SVG without `width` and `height` attributes

Needs visual debugging in DevTools to identify which container shifts.
Not investigated further in this pass.

---

## Endpoint duplication (cold dashboard load — pre v21.0.2 trace)

| Endpoint | Calls on cold load | Calls on warm reload |
|---|---:|---:|
| `/api/projects` | 6 | 2 |
| `/api/network/events` | 6 | 2 |
| `/api/hosts/budget` | 3 | 1 |
| `/api/plugins` | 2 | 1 |
| `/api/bridge/status` | 2 | 1 |
| `/api/trajectories` | 2 | 1 |
| `/api/ignored-projects` | 2 | 1 |
| Total fetches | **44** | 14 |

Multiple Alpine components fetch the same endpoint independently. Even
with sub-ms warm responses this adds ~150 KB of duplicate transfer and
makes browser DevTools harder to read. Fix is an `Alpine.store('hmData')`
that owns the canonical fetches and exposes derived view-state.

---

## verify-ci gate misfire (the v21.0.1 regression)

**What happened:** When `git push origin v21.0.x` runs, two CI workflow
runs are created on the same commit SHA:

1. `name=CI` triggered by `push` on `main` branch  → conclusion=success
2. `name=CI` triggered by `push` on `v21.0.x` tag → conclusion=failure

Both have identical `created_at` timestamps. My `sort_by(.created_at) | last`
query is non-deterministic when timestamps tie — GitHub happened to return
the failure run last, so the gate read "failure" and blocked publish.

The tag-push CI run failed because **macOS Python 3.11 matrix flaked
once**; the main-push CI run had all jobs green. Different shard, same SHA.

Two fixes needed:

1. **`ci.yml` should not run on tag push.** Tags trigger `publish.yml` only.
   Currently `on: push: tags: ["v*"]` is set, which double-fires CI.
2. **`publish.yml`'s `verify-ci` should filter the CI run by `event=push`
   AND `head_branch=main`,** not just by workflow name. Defensive even if
   tag-CI is removed (e.g. workflow_dispatch could create another run).

---

## Recommended fixes for v21.0.3 (NOT yet implemented)

**Tier 1 — release-blocking process bug**
1. `ci.yml`: remove `tags: ["v*"]` from `on:` triggers.
2. `publish.yml`: tighten `verify-ci` filter to `event="push", head_branch="main"`.

**Tier 2 — universal cold-start fix**
3. `routes.py`: wrap `discover_projects()` calls in `asyncio.to_thread` for
   `/api/projects`, `/api/ignored-projects`, `/api/kpi` cache-miss paths.
4. Startup warmup task (`@app.on_event("startup")`) that prime-builds the
   projects + ignored caches in the background so the first user request
   is already warm.

**Tier 3 — discover_projects internal speedup**
5. Parallelise `_git_last_commit` across projects via `ThreadPoolExecutor`
   (62 sequential subprocesses → ~16-wide pool → ~880 ms → ~60 ms).
6. Audit `_detect_language_from_extensions` rglob fallback — why 12/62
   projects hit it; can the manifest detector cover more cases?

**Tier 4 — defer (UI work)**
7. `/projects/<name>` CLS 0.30 — visual debug + reserve space for the
   graph block / trajectory list to stop the post-paint shift.
8. Alpine.store dedup — 44 fetches cold → ~10. Bigger refactor.

---

## What to do about v21.0.2

Three options:

| Option | Cost | Result |
|---|---|---|
| Cut v21.0.3 with Tier 1 fixes only | 30 min | v21.0.3 on PyPI; v21.0.2 stays tagged but unpublished |
| Cut v21.0.3 with Tier 1+2 | ~2 h | v21.0.3 on PyPI with broader perf wins |
| Manual `workflow_dispatch` to publish v21.0.2 + a follow-up commit with Tier 1 fix | 20 min | v21.0.2 on PyPI; gate fix lands separately |

Tier 3 + Tier 4 are bigger work — a v21.0.4 patch or part of a v22 line,
depending on operator priority.

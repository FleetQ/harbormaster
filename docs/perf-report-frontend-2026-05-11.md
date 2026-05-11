# Harbormaster Dashboard — Frontend Performance Report

**Date:** 2026-05-11
**Subject:** `http://127.0.0.1:7531/` running `harbormaster-mcp 21.0.0` (PyPI installed; v21.0.1 in flight)
**Reviewer:** Claude Opus 4.7 via Chrome MCP performance tracing
**Viewport:** 1280×800 (effective 1040×663)

---

## Headline numbers

| Web Vital | Cold load | Warm load | Target | Verdict |
|---|---:|---:|---:|---|
| **LCP** (Largest Contentful Paint) | 448 ms | 348 ms | <2500 ms | ✅ Good |
| **FCP** (First Contentful Paint) | 284 ms | 236 ms | <1800 ms | ✅ Good |
| **CLS** (Cumulative Layout Shift) | 0 | 0 | <0.1 | ✅ Perfect |
| **DOMContentLoaded** | 414 ms | 317 ms | — | — |
| **Load event** | 474 ms | 406 ms | — | — |
| **TTFB** | 3.4 ms | <1 ms | <600 ms | ✅ Good (loopback) |

Core Web Vitals are all "Good" out of the gate. **But the dashboard hides a serious request-handling bottleneck once you look past first paint.**

---

## Status: NEEDS WORK

Strong paint metrics mask a backend serialization bug and aggressive over-fetching:

- **44 fetch calls on cold load** — for a 30-project workspace. After dedup this should be ~10.
- **`/api/graph?format=cytoscape` takes 1.93 s in isolation** — solo curl. Every other endpoint runs <10 ms in isolation.
- **Concurrent endpoints serialize behind `/api/graph`** — the cold load shows 9 distinct API endpoints all clustering around 5800 ms response time even though their solo latency is single-digit ms. Same pattern on warm load (~2060 ms).
- **6× duplicate `GET /api/projects` and 6× duplicate `GET /api/network/events`** on cold load.

The single Python worker on `:7531` is blocked by sync filesystem traversal inside `/api/graph`, so every other request queues behind it.

---

## Detailed findings

### 🔴 CRITICAL — `/api/graph` blocks the event loop

```
Isolated curl:                  1.93 s
Browser load (cold):            5823 ms  (queued behind/sharing slot with itself)
Browser load (warm):            2064 ms  (warm OS cache helps a little)
```

`/api/graph` does heavy synchronous work: walk every project root, parse `package.json` / `Cargo.toml` / `pyproject.toml` / `uv.lock` / `poetry.lock` / `composer.lock` etc., extract dependencies, build the graph. With FastAPI on uvicorn, **sync work inside an async handler blocks the event loop**, so every other request waits.

Evidence: on the cold trace, ALL of these clustered around ~5800 ms even though their solo latency is <10 ms — they were waiting for the graph handler to release the loop:

| Endpoint | Solo curl | Browser (cold) | Browser (warm) |
|---|---:|---:|---:|
| `/api/projects` | 1.5 ms | 5836 ms | 11 ms |
| `/api/ignored-projects` | — | 5834 ms | — |
| `/api/trajectories?limit=20` | — | 5832 ms | — |
| `/api/hosts/budget` | — | 5831 ms | — |
| `/api/plugins` | 8.5 ms | 5829 ms | 13 ms |
| `/api/bridge/status` | 1.3 ms | 5827 ms | — |
| `/api/network/events?limit=10` | 1.4 ms | 5826 ms | 2060 ms |
| `/api/settings/accent` | <1 ms | — | 2057 ms |
| **`/api/graph?format=cytoscape`** | **1929 ms** | **5823 ms** | **2064 ms** |

The fact that warm load STILL shows the cluster (~2060 ms) confirms it's not just OS cache — it's structural serialization inside `/api/graph`.

**Recommended fixes (any one is a big win; do them together for max effect):**

1. **Offload to a thread**: wrap the lockfile-parsing core in `await asyncio.to_thread(...)` so the event loop stays responsive while filesystem work runs on a worker thread. ~1 hour fix.
2. **TTL cache the graph result**: dependency graphs change rarely (only when an operator adds/removes a project or edits a manifest). 60-second in-process LRU on the `/api/graph` handler reduces post-cold cost to ~0. ~30 minutes.
3. **Lazy-load**: don't fetch `/api/graph` until the operator switches to a tab that needs it. Today the dashboard fires it on every page load even though the graph might not be the active view. ~45 minutes (Alpine `x-init` move).

### 🟠 HIGH — Aggressive over-fetching on cold load

| Endpoint | Cold calls | Warm calls |
|---|---:|---:|
| `/api/projects` | **6** | 2 |
| `/api/network/events` | **6** | 2 |
| `/api/hosts/budget` | 3 | 1 |
| `/api/plugins` | 2 | 1 |
| `/api/bridge/status` | 2 | 1 |
| `/api/trajectories` | 2 | 1 |
| `/api/ignored-projects` | 2 | 1 |
| (Total fetches) | **44** | 14 |

Multiple Alpine components fetch the same endpoints independently. Each component should consume from a shared Alpine store (or a single `x-data` factory call at the top) rather than wiring its own `fetch`.

**Recommended fix**: introduce an `Alpine.store('hmData')` that owns the canonical fetches and exposes derived view-state. Child components read from the store. Single fetch per endpoint per refresh — cuts initial network volume by ~3×, ~150KB of duplicate transfer.

### 🟠 HIGH — Total transfer / parse cost

| Metric | Cold | Warm |
|---|---:|---:|
| Resources requested | 39 | 14 |
| Total transfer | 521 KB | (mostly cached) |
| Total decoded | 1.24 MB | — |
| Initial HTML | 191 KB | 191 KB |

The HTML payload is 191 KB. That's a lot for a dashboard shell — server-side renders the full sidebar (32 projects × link + button), inspector pane, and all panels. Most of it isn't visible on the initial fold.

**Recommended fixes:**
- **Sidebar virtualization** (or simply collapse-by-default for groups beyond the first 5). The sidebar currently renders 49 interactive elements upfront.
- **Inspector pane lazy mount** — only render the inspector contents when expanded.
- Once the duplicate fetches are gone (HIGH-1 above), `~150 KB` of the cold transfer disappears naturally.

### 🟡 MEDIUM — Mermaid graph never rendered

The cold trace shows `mermaid_rendered: false` and `cytoscape_container_present: true`. The v21.0.0a9 toggle defaults to Cytoscape, which is reasonable, but the `<pre class="mermaid">` element is still in the DOM as a fallback target — confirm it's hidden (not parsed/rendered) when Cytoscape is the active renderer. If Mermaid keeps initializing in the background, that's wasted JS work even though it's invisible.

### 🟢 LOW / Informational

- **0 long tasks (>50 ms)** captured on either cold or warm load. Main thread isn't blocked by JS; the perf cost is server-side wait, not client compute.
- **CDN-loaded scripts** (Alpine, Mermaid, Tailwind preview build) — 5 scripts total, all from `unpkg.com`. Move to local-hosted in a future patch for offline use + cache reliability, but not urgent.
- **CLS = 0** — the workspace shell layout is set in CSS grid with stable column dimensions, so no shift. Keep doing whatever you're doing.

---

## Recommendations — prioritized

| Priority | Fix | Effort | Expected impact |
|---|---|---|---|
| **1** | `asyncio.to_thread()` around `/api/graph` lockfile parsing | ~1 h | Unblocks event loop; concurrent endpoints stay <10 ms |
| **2** | TTL cache on `/api/graph` (60 s in-process LRU) | ~30 min | Warm reloads drop /api/graph to ~0 ms |
| **3** | Lazy-load `/api/graph` (only when graph tab visible) | ~45 min | Initial cold load drops 1.9 s of wait |
| **4** | `Alpine.store('hmData')` — dedupe overlapping fetches | ~2 h | Cuts 44 → ~10 fetches; -150 KB transfer cold |
| **5** | Sidebar collapse-by-default beyond first N projects | ~1 h | HTML payload 191 KB → ~80 KB |
| **6** | Inspector lazy-mount when expanded | ~1 h | Minor; pairs with #5 |

Fixes 1+2+3 stack: a v21.0.2 patch could realistically land **all `/api/*` warm calls under 20 ms total** including the graph. That's the single most user-visible improvement available for the dashboard.

---

## How to reproduce

```js
// Capture LCP / FCP / CLS on a fresh load:
new Promise((resolve) => {
  let lcp = null, cls = 0;
  new PerformanceObserver(l => l.getEntries().forEach(e => lcp = e.startTime))
    .observe({type: 'largest-contentful-paint', buffered: true});
  new PerformanceObserver(l => l.getEntries().forEach(e => { if (!e.hadRecentInput) cls += e.value; }))
    .observe({type: 'layout-shift', buffered: true});
  setTimeout(() => resolve({lcp, cls}), 4000);
});
```

For endpoint serialization, hit the dashboard in Chrome DevTools → Network → reload and watch how long the API calls take. The "Waiting (TTFB)" column will show ~2 s on every concurrent call even though the endpoint logic itself is fast.

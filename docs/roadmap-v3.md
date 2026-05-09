# Harbormaster v3 Roadmap

**Drafted:** 2026-05-09 (after v2.1.0 GA shipped same day)

v2 widened the platform to multi-backend, plugin-extensible, lockfile-aware,
with cross-host recall and per-token bridge streaming. v2.1 layered the
operator UI on top.

v3 closes loops left open by v2 (the FleetQ → harbormaster `agent.request`
publish surface, live runtime state in `/api/bridge/status`), polishes the
operator surface (mobile graph, inline ask, cross-section refresh, URL state),
hardens concurrency (parallel cross-host recall, pysher worker thread, UI
token plumbing), and finally adds Playwright headless browser tests.

Single monolithic v3.0 line — every phase ships as `v3.0.0a1` … `v3.0.0a10`,
each with its own branch + sprint retro, then `v3.0.0` GA.

## Out-of-scope for v3 (defer to v4+)

Carried forward from v2 retros, plus new deferrals:

- Tauri / Electron desktop UI wrapper (still no demand; UI is operator-only)
- Relay-binary path (Path B) (Path C HTTP tunnel covers the use case)
- Built-in IDE extension (VS Code / JetBrains) — MCP server already works
  with any MCP-compatible client
- LLM-based triple extraction for remote hosts (heuristic only over SSH)
- Auto-reembed on drift detection (operator decides; CLI exists since v2.0.0a2)
- Cross-model vector translation (use reembed instead)

## Phases

### Phase 1 — `agent.request` → MCP dispatcher (`v3.0.0a1`)

v2.0.0a7 wired per-token streaming **outbound** (harbormaster → FleetQ
Bridge → Pusher). The inbound counterpart (`agent.request` events from
FleetQ Bridge into local MCP tool dispatch) was deferred; v3.0.0a1 closes it.

- Subscribe to `agent.request` events on the Reverb/Pusher channel
- Route incoming requests to the existing MCP tool registry
- Send response via the existing relay (`chunk` + `result` events from a7)
- Error envelope: structured `{error, code, request_id}` propagated to caller
- Auth: same token gate as the rest of the bridge surface
- Tests: stub Pusher event → dispatcher → captured outbound chunks
- FleetQ-side emission is driven via harbormaster's own `delegate_task`
  MCP tool (eat-our-own-dog-food smoke); no agent-fleet PR required for ship

### Phase 2 — Live FleetQ runtime state in `/api/bridge/status` (`v3.0.0a2`)

`/api/bridge/status` is currently config-derived only (returns whether the
bridge is *configured*, not whether it is *connected*). Phase 2 wires real
runtime state.

- New `BridgeRuntimeState` (Pydantic): `connected`, `last_heartbeat`,
  `last_error`, `pending_requests`
- Cross-process plumbing: file-based (atomic writes to `~/.harbormaster/bridge-state.json`)
  rather than shared memory — simpler and survives crashes for diagnosis
- UI panel updates: badge color follows `connected`; tooltip shows last heartbeat age
- TTL on state read: stale (>30s) → render as "stale" not "down"
- Tests: writer + reader contract, stale detection, missing file fallback

### Phase 3 — pnpm-lock + yarn.lock parsers (`v3.0.0a3`)

Extends v2.0.0a1 lockfile parsing. Both formats deferred at v2 ship time
because pnpm-lock.yaml requires YAML parsing and yarn lockfiles split
between v1 (custom format) and Berry (YAML).

- pnpm-lock.yaml: `packages` map → `(name, version)` tuples
- yarn.lock v1: custom format parser (peg-style)
- yarn.lock berry: YAML map (`__metadata.version: 6+` → Berry)
- All gated through existing `graph.lockfile` registration pattern
- Tests: real-world fixtures from popular OSS projects

### Phase 4 — Parallel cross-host recall (`v3.0.0a4`)

`recall_qa(host="all")` currently fans out sequentially via SSH. With N
hosts and ~500ms SSH connection overhead each, this is N× slower than it
needs to be.

- New `[recall] parallel = true` + `max_workers = 4` config (default sequential)
- `concurrent.futures.ThreadPoolExecutor` for the SSH fan-out
- Per-host timeout (default 5s) to avoid one slow host blocking the merge
- Score-merge unchanged
- Tests: stub two hosts with artificial delays; assert wall-clock < single-host × N

### Phase 5 — Pysher worker-thread offloading (`v3.0.0a5`)

Pysher (the Pusher Python client) runs on the same event loop as FastAPI's
async server. Long-running event handlers can block the loop. Phase 5
moves pysher to a dedicated worker thread.

- New `BridgeWorker` thread owning the pysher client
- Bidirectional queue: `inbound_queue` (events for FastAPI) + `outbound_queue` (publishes)
- Graceful shutdown via `Event` flag
- Tests: simulated long-running handler; assert FastAPI route latency unchanged

### Phase 6 — Token plumbing for bearer-protected UI installs (`v3.0.0a6`)

When `HARBORMASTER_UI_TOKEN` is set, the UI rejects unauthenticated calls.
But internal UI routes that fan out to MCP tools (e.g. `/tools/fan-out`
→ `delegate_task`) currently miss the token plumbing.

- Internal token resolution helper: prefer ambient request token, fall back
  to env var, fail explicit
- All internal MCP dispatch in `ui.routes` uses the helper
- Tests: bearer-protected install + UI fan-out → all sub-requests carry token

### Phase 7 — Inline ask form on dashboard cards (`v3.0.0a7`)

`_partials/ask_form.html` currently renders only on the project detail page.
Move it to the dashboard project grid (collapsible per card) so operators
can ask without navigating.

- Reuse `_partials/ask_form.html` partial directly
- Per-card Alpine `x-data` scope (no global state collisions)
- Card grid keeps responsive layout when card expands
- Tests: dashboard renders ask form per card; SSE form streaming works

### Phase 8 — Ask→trajectory cross-section refresh events (`v3.0.0a8`)

Today, after asking a project a question on the detail page, the trajectory
section below requires a manual refresh to see the new entry. Phase 8 wires
custom DOM events: ask form completion → trajectory section reload.

- Alpine `$dispatch('hm:trajectory:dirty', { project })` from ask form on stream end
- Trajectory partial listens via `x-on:hm:trajectory:dirty.window`
- Re-fetch via `/api/trajectories?project=<name>&limit=10`
- Tests: simulated event → trajectory partial re-renders new entry

### Phase 9 — Mobile-optimized graph + URL state encoding (`v3.0.0a9`)

Two related UX issues:
1. Mermaid graph is non-interactive on mobile (no zoom/pan)
2. Fan-out form filters reset on page reload (no URL state)

- Mermaid responsive: pinch-zoom + drag-pan on touch (existing Mermaid 10.9 supports it via init config)
- Fan-out form: read from + write to URL search params on submit
- Sharable links: copy current URL → recipient sees same form pre-filled
- Tests: URL → state → URL round-trip for fan-out form

### Phase 10 — Headless browser tests (Playwright) (`v3.0.0a10`)

UI shipped in v2.1 with smoke jobs that only check HTTP status. Phase 10
adds real browser-driven tests for the dashboard, project detail, fan-out,
and ask form flows.

- New `[ui-test]` extra in pyproject.toml (`playwright>=1.45`)
- Tests in `tests/ui/test_browser_*.py` (gated by `pytest -m browser`)
- New CI smoke job `smoke-ui-browser` (Ubuntu only, Playwright Linux runners)
- Cover: dashboard renders, project detail navigates, ask form streams,
  fan-out form submits, trajectory refreshes after ask

### v3.0.0 GA

Drop alpha. Write `docs/sprint-retro-harbormaster-v3.0.0.md`. Bump README
status. No new code in the GA tag — just the version bump (mirroring v1 + v2 GA).

## Already-decided (don't re-litigate)

- Same release flow as v1/v2: branch per phase, **local merge** (no PR — per
  user feedback 2026-05-09), bump version, retro, tag, push, PyPI auto-publishes
- All new behavior is opt-in via config gates (matching v1/v2 discipline)
- No breaking changes to the v2 tool surface; new tools / new args only
- mypy --strict + ruff stay non-negotiable
- UI stack stays no-build (Jinja + Tailwind + Alpine + HTMX + Mermaid via CDN)

## Order rationale

Phases ordered to minimize cross-phase coupling:
- a1-a2 (dispatcher + live state) close v2-deferred loops first; everything
  else can build on the live state
- a3 (lockfile parsers) is purely additive to v2.0.0a1 — drop in anywhere
- a4-a5 (parallel recall, pysher worker) tighten the threading story before
  layering more UI on top
- a6 (token plumbing) precedes new UI work that hits internal MCP dispatch
- a7-a9 (inline ask, cross-section events, mobile/URL state) are pure UI
- a10 (Playwright) ships LAST so the test surface covers the cumulative UI

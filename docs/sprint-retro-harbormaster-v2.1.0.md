# Sprint Retro — Harbormaster v2.1.0 (GA)

**Date:** 2026-05-09
**Theme:** **`v2.1.0` GA shipped.** Drop of the alpha suffix after
six v2.1 alpha tags (a1 → a6), all delivered the same evening as
v2.0.0 GA + v2.0.1 patch. The dashboard graduates from a read-only
project list into a working local operator console — every backend
signal harbormaster's been computing since v1 finally has a
browser-side surface.

## What landed (the full a1→GA arc)

| Tag | Capability |
|-----|------------|
| `v2.1.0a1` | Mermaid project graph render + FleetQ Bridge / plugin status panels + `/api/graph?transitive=true` toggle |
| `v2.1.0a2` | `/projects/{name}` detail page rendering git log + Serena memories + path |
| `v2.1.0a3` | Recall search inline on dashboard via new `/api/recall` endpoint, cross-host fan-out via `host="all"` |
| `v2.1.0a4` | "Ask this project" SSE form on detail page (fetch streaming + AbortController) |
| `v2.1.0a5` | `delegate_task` form + `/tools/fan-out` page with multi-select project chips |
| `v2.1.0a6` | "Recent Q&A" trajectory list per project + `QAStore.list_recent()` + `/api/trajectories` endpoint |
| **`v2.1.0`** | **GA — alpha suffix dropped, no new code** |

## Capabilities at GA

### Dashboard

- 5 distinct sections: status strip (Bridge + Plugins), recall
  search, project graph (Mermaid), and project grid (clickable cards)
- Project graph supports `include_dev_deps` and `transitive`
  (lockfile) toggles — calls back to v2.0.0a1's transitive flag
- Bridge panel reports config-derived state with token-presence
  detection
- Plugin panel categorizes entry points (loaded / not-allowlisted /
  disabled / no-dist-name / missing) and links to v2.0.1's CLI
  output

### Project detail page (`/projects/{name}`)

- Server-rendered Jinja from `_local_status` / `_remote_status`
- Inline "Ask" form (SSE streaming via `POST /mcp/{server}` with
  fetch + manual SSE parse)
- Inline "Delegate" form with separate `task` and `deliverable`
  textareas
- "Recent Q&A" section reading from `/api/trajectories` —
  collapsible Q&A pairs, relative timestamps, configurable limit

### Fan-out page (`/tools/fan-out`)

- Multi-project chip selection with all/none toggles
- Configurable `max_concurrency` and `max_turns`
- Optional host filter from `[hosts.*]`
- Aggregated result view (fan_out_ask returns one combined payload)

### Endpoints

- `GET /api/bridge/status` — config-derived FleetQ state
- `GET /api/plugins` — entry-point categorization
- `GET /api/recall` — `recall_qa` MCP tool wrapper
- `GET /api/trajectories` — chronological per-project Q&A list
- `GET /api/graph` — gained `transitive` query param
- `GET /tools/fan-out` — fan-out HTML page
- `GET /projects/{name}` — project detail HTML page

### Library API

- `QAStore.list_recent(project, limit)` — public method for
  chronological history queries

## Real numbers (cumulative across v2.1)

- 6 alpha PRs opened / merged (#23 #24 #25 #26 #27 #28)
- 34 new unit tests added across the six phases (510 → 554 pass, 1 skip)
- mypy --strict: 45 → 46 source files, clean across all phases
- ruff: clean across all phases
- Backwards-incompatible changes: 0 (every new behaviour is
  additive — JSON wire shapes preserved with new optional fields)
- 7 published versions: v2.1.0a1 → v2.1.0a6 → v2.1.0
- New templates: `project_detail.html`, `fan_out.html`,
  `_partials/ask_form.html`, `_partials/delegate_form.html`
- New endpoints: `/api/bridge/status`, `/api/plugins`,
  `/api/recall`, `/api/trajectories`, `/projects/{name}`,
  `/tools/fan-out`
- Lines added: ~2,000 across all six PRs (mostly templates + JS)
- Time from v2.0.0 GA to v2.1.0 GA: same evening (autonomous run)

## What worked

- **One PR per phase + squash-merge** (proven across v1, v2.0,
  v2.0.1, now v2.1). Every alpha tag points at exactly one squashed
  commit, no fixup chains.

- **Per-phase retro AS PART of the ship commit.** Same playbook as
  prior majors: the retro is written WITH the version bump, while
  details are fresh. The GA retro is then a synthesis pass.

- **Server-render where possible, Alpine where needed.** Project
  detail page is pure Jinja → no JS until the user hits an inline
  form. Dashboard is Alpine-driven where it has to be (async
  /api/* fetches), but each x-data block is local — no global
  state, no router, no build step.

- **fetch streaming over EventSource.** EventSource is GET-only,
  so the v2.1.0a4 ask form uses `fetch().body.getReader()` +
  manual SSE block parsing. ~30 LOC of consumer code; bonus is
  AbortController support for "stop" buttons.

- **Soft-fail uniform shape.** Three v2.1 endpoints (recall,
  trajectories, bridge status) all return `{enabled: bool,
  message?: str}` for off / missing / error paths. Dashboard's
  amber-text "message" handler works the same way for all three.
  Future endpoints should mirror this.

- **JSON tojson for safe template embedding.** Every
  `{{ project_name | tojson }}` in an Alpine x-data initializer
  prevents XSS even if a project name has weird chars. No manual
  escape gymnastics.

- **Stable secondary sort on history queries.** Adding `id DESC`
  as the tiebreaker for same-second created_at saved a flaky test
  and codified deterministic chronological ordering.

- **Partial templates for SSE forms.** `_partials/ask_form.html`
  and `_partials/delegate_form.html` are reusable Alpine
  components. The detail page includes both; future phases
  (dashboard inline, /tools/{name} pages) can reuse without
  duplicating the SSE consumer.

- **Mermaid 10.9.1 ESM via CDN.** Pinned URL keeps it
  reproducible. Zero npm. Re-rendering on toggle change is one
  `mermaid.run({ nodes: [el] })` call.

## What to change / next (v2.2 / v3 candidates)

- **No mobile-optimized graph.** Wide dependency graphs need
  horizontal scroll on phones. A "compact mode" toggle would help.
- **No URL state.** Reload loses recall queries, fan-out
  selections, trajectory limits. URL-encoded query state would
  improve shareability and back-button behaviour.
- **No live runtime FleetQ state.** /api/bridge/status reports
  config only — runtime session_id / last heartbeat lives in
  harbormaster-mcp's process. Cross-process state requires a
  shared state file or a sidecar.
- **No "ask form → trajectory refresh" wiring.** After running ask
  on detail page, trajectory section is stale until reload. Custom
  events or window.dispatchEvent would close the loop.
- **No inline ask form on dashboard cards.** Currently you have
  to click into detail page first. Each card could expand inline.
- **No headless browser tests.** All UI tests trust selectors +
  JSON contracts; full DOM behaviour is untested. Adding
  Playwright would catch JS regressions but adds CI cost.
- **No token plumbing for bearer-protected installs.** Loopback
  no-auth (the common dev setup) works as-is. Bearer-protected
  installs need fetch-header injection via meta tag or cookie
  bridge.

## Out-of-scope (still — pushed past v3 too)

- Tauri / Electron desktop UI wrapper
- Relay-binary path (Path B)
- agent.request → MCP dispatcher wiring
- LLM-based extraction for remote hosts
- Built-in IDE extension

## Release flow used (proven across v1, v2.0, v2.0.1, v2.1)

```
1. Branch:   feat/v<N>.<P>-<phase-name>
2. Implement, test (mypy strict + ruff + pytest); local pre-flight
3. Commit + push; open PR
4. Watch CI → squash-merge to main
5. Bump __version__ on main
6. Write docs/sprint-retro-harbormaster-v<N>.<P>a<K>.md from TEMPLATE
7. Commit "ship: bump to <N>.<P>a<K> + sprint retro"
8. Tag v<N>.<P>a<K> and push tag (PyPI Trusted Publishing fires)
9. Verify on https://pypi.org/project/harbormaster-mcp/
10. Repeat for next phase
11. After last alpha → GA: bump to <N>.<P>.0, write GA retro, tag v<N>.<P>.0
```

This shape worked end-to-end three times in one autonomous session
(v2.0 GA, v2.0.1 patch, v2.1 GA). The pattern compounds: by alpha 4
the muscle memory makes each phase shippable in one focused work
block.

## Version landscape after v2.1.0

| Tag | What it means |
|-----|---------------|
| `v1.0.0` | Original local + SSH + Live UI + FleetQ Bridge HTTP-tunnel + Q&A history + project graph + auto-grounding |
| `v2.0.0` | Lockfile transitive deps · embedding upgrade · multi-backend · plugin API · LLM triples · cross-host recall · Bridge per-token streaming |
| `v2.0.1` | SSH argv quoting + pysher kwarg + plugin warn-missing + plugins list CLI |
| `v2.1.0` | UI sprint — dashboard becomes operator console |

Latest stable: **`v2.1.0`** on PyPI.

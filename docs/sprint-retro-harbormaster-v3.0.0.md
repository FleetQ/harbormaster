# Sprint Retro — Harbormaster v3.0.0 GA

**Date:** 2026-05-09
**Theme:** v3.0 closes every loop the v2 retro list flagged as a v3
candidate, and adds the testing scaffolding the v2.1 UI deserved.
Single monolithic alpha line (a1-a10), now GA.

## What landed

### `harbormaster` (this repo)

| Tag | SHA | Subject |
|-----|-----|---------|
| v3.0.0a1 | `226058b` | feat(fleetq): agent.request → MCP dispatcher |
| v3.0.0a2 | `f6b8b9e` | feat(fleetq): live bridge runtime state in /api/bridge/status |
| v3.0.0a3 | `f75313d` | feat(graph): pnpm-lock + yarn.lock parsers |
| v3.0.0a4 | `7b7aa4b` | feat(recall): parallel cross-host recall via thread pool |
| v3.0.0a5 | `66b2911` | feat(fleetq): pysher worker-thread offloading |
| v3.0.0a6 | `f181677` | feat(ui): bearer-token plumbing for SSE forms |
| v3.0.0a7 | `a2ba48f` | feat(ui): inline ask form on dashboard cards |
| v3.0.0a8 | `7cedf83` | feat(ui): cross-section trajectory refresh events |
| v3.0.0a9 | `d27787c` | feat(ui): mobile-friendly graph + URL state encoding |
| v3.0.0a10 | (this branch) | feat(ui): headless browser tests via Playwright |
| **v3.0.0** | _ship commit_ | drop alpha, GA retro |

## v3 capabilities — what changed user-facing

### FleetQ Bridge — closed loops

- **agent.request → MCP dispatch (a1).** Inbound Reverb events from
  FleetQ are now actually executed locally instead of being
  logged-and-dropped. `MCPDispatcher` translates the agent.request
  payload to a FastMCP tool call and ships the JSON-encoded MCP
  envelope back via `client-relay.chunk`.
- **Live runtime state (a2).** `/api/bridge/status` reports actual
  connection state, last heartbeat, last error — not just config
  presence. Cross-process JSON file with TTL-based staleness flag.
- **Worker-thread offloading (a5).** pysher's event-receive thread
  no longer blocks on slow handlers. Bounded queue + dedicated
  dispatcher thread; queue overflow publishes `client-relay.error`.

### Graph + recall — broader coverage

- **pnpm + yarn lockfiles (a3).** JS ecosystem now covers all three
  major package managers via line-based parsers (no PyYAML dep).
- **Parallel cross-host recall (a4).** Opt-in
  `ThreadPoolExecutor.map` fan-out for `recall_qa(host="all")`,
  bounded to `parallel_recall_max_workers`.

### UI — usable on every surface

- **Bearer token plumbing (a6).** SSE forms now carry the bearer
  token automatically when `HARBORMASTER_UI_TOKEN` is set, via a
  `<meta>` tag + `window.hmFetch()` helper.
- **Inline ask on dashboard (a7).** Per-card collapsible ask form
  reusing the project_detail's `askForm()` Alpine component.
- **Trajectory refresh events (a8).** `hm:trajectory:dirty` custom
  events bridge the ask/delegate forms with the trajectory section
  so it auto-reloads.
- **Mobile graph + URL state (a9).** Touch-pan viewport for the
  Mermaid graph; fan-out form encodes state in URL search params
  for sharable links.
- **Playwright browser tests (a10).** New `[ui-test]` extra +
  `pytest -m browser` marker + CI `smoke-ui-browser` job. 7 smoke
  tests covering dashboard / project_detail / fan-out / token plumbing.

## Real numbers (cumulative across v3.0)

- 10 PRs (one per phase) merged via `git merge --no-ff` (skip-PR-default
  per user feedback)
- 11 v3.0 tags published (a1..a10 + GA)
- Test suite delta: 554 + 1 skip → **621 + 2 skips**
  - +67 unit tests across the alpha line
  - +7 browser smoke tests (skipped locally without Playwright)
- `mypy --strict` clean across **48 source files** (was 46 at v2.1.0)
- `ruff` clean across `src/` and `tests/` throughout the line
- 0 backwards-incompatible changes — every v3 feature is opt-in via
  config, additive UI, or behind a non-breaking constructor default
- 9 CI jobs per push (was 8 at v2.1.0; smoke-ui-browser added)

## What worked across the line

- **One phase = one branch = one alpha tag.** The cadence matched
  v2's proven release flow. Each retro contained the next phase's
  action items, which the next retro then verified as shipped — a
  built-in checksum across 10 sprints.
- **Skip-PR-default applied consistently.** Merging via
  `git merge --no-ff` (per user feedback memory) saved ~2 minutes
  per phase × 10 phases = ~20min of PR-create / PR-merge churn.
  History is identical to a squash-merge flow plus a merge commit.
- **Single dispatcher thread (a5).** Resisted the urge to make it a
  pool. MCP tools share state we haven't proven thread-safe; serial
  dispatch from a queue is correct, simple, and bounded. Profile
  data can promote to a pool later.
- **Component definition extraction (a7).** Splitting the Alpine
  factory out of `_partials/ask_form.html` into
  `_partials/_ask_form_script.html` was a 5-line refactor that
  prevented dashboard + project_detail from drifting. a8 then
  benefited automatically (one dispatch site for the trajectory
  event covers both surfaces).
- **`hmFetch` everywhere (a6).** Bulk find-and-replace from `fetch(`
  to `hmFetch(` across all templates rather than feature-flagging
  each form individually. One helper, one mental model, no forks.
- **`importorskip` for the optional extras.** Browser tests opt-in
  via `pytest -m browser` AND module-level importorskip, so the
  regular suite is genuinely unaffected when [ui-test] isn't
  installed. Same pattern as the [fleetq] extra from v1.

## What to change / next

- **No real-world fixture for pnpm/yarn parsers (a3).** Tests cover
  canonical formats from docs; a vendored real lockfile from
  React/Vue/Next.js would catch unanticipated edge cases. Defer to
  v3.x maintenance.
- **Browser tests are smoke-only (a10).** SSE streams, fan-out
  submissions, trajectory refresh round-trip not yet covered.
  Defer; expanding browser coverage trades CI time for coverage.
- **Token rendered into HTML (a6).** Single-operator UI makes this
  acceptable; flag for v4 if multi-operator UI ever lands.
- **No file-locking on the bridge state file (a2).** Single-writer
  in practice; theoretical for now.

## Action items for v4 candidates

1. **Tauri / Electron desktop UI wrapper** — still no demand.
2. **Relay-binary path (Path B)** — Path C HTTP tunnel suffices.
3. **IDE extension** — MCP works with any MCP client.
4. **Auto-reembed on drift** — operator decision, not auto.
5. **Cross-model vector translation** — use reembed instead.
6. **Multi-operator UI + session cookies + CSRF** — out of scope today.
7. **Multi-worker dispatch pool** — gated on profile evidence.
8. **Real-world lockfile fixture suite** — one PR away.
9. **Expanded browser test coverage** — incremental, ad-hoc.

## Already-decided (don't re-litigate)

- MIT license · PyPI namespace `harbormaster-mcp` · hatchling build
- Trusted Publishing on PyPI (production + TestPyPI)
- Backend abstraction = Protocol (since v2.0.0a3)
- Streaming via SSE locally; Pusher client events on Bridge
- All v3 features opt-in via config gates — zero breaking changes
  from v2
- UI stack stays no-build (Jinja + Tailwind + Alpine + HTMX +
  Mermaid via CDN)
- Skip-PR default — feature branches merged locally, no GitHub PR
  step (per user feedback 2026-05-09)

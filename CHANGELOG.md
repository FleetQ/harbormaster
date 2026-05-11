# Changelog

All notable changes to **harbormaster-mcp** (the `harbormaster` project on
PyPI) are documented here. Format follows [Keep a Changelog
1.1.0](https://keepachangelog.com/en/1.1.0/). The project follows a
calendar-cadence "every alpha is a PyPI release, every major is a
no-code GA promotion" model — see [README §Versioning](README.md#versioning).

Per-version narrative retros (the why behind each change) live under
[`docs/sprint-retro-harbormaster-v*.md`](docs/). This file is the
user-facing summary of what shipped per major release.

Dates are the GA tag dates (UTC, taken from `git log`). Each major
entry lists the alpha tags that built up to GA.

---

## [Unreleased]

_v20 sprint in flight: trajectoryList tojson hotfix, bleach pipeline audit,
editable budget settings, inspector drag-resize, light-mode contrast fixes,
mobile responsive drawer, tabs extension to dashboard/network/dispatcher._

---

## [19.0.0] - 2026-05-11

**Theme:** **Dramatic UI revamp.** Operator's "I see no difference from v8"
critique answered with a multi-pane workspace, Linear-violet visual identity,
compact density, and a real (rather than over-reported) memories editor.
Anti-slop protocol: every alpha required a Playwright screenshot to disk
before commit — caught the v19.0.0a8 → a9 hotfix in the act.

Nine PyPI versions across the sprint (a1, a2, a3, a4, a5, a7, a8, a9, GA).
The a6 number was skipped because Phase 7 (a7 SSE feed) and Phase 6 (memories
editor) raced; semver monotonicity required the memories editor to land as a8
once a7 was already published. v20 forwards retain the a6-skip lesson.

### Added
- **Three-column workspace shell** (`v19.0.0a1`) — fixed topbar / 240px
  sidebar / fluid main / 320px collapsible inspector. CSS Grid + landmark
  IDs (`hm-topbar`, `hm-sidebar`, `hm-main`, `inspector`). Inspector
  collapse persists in `localStorage`.
- **Tab system on `/projects/<name>`** (`v19.0.0a2`) — Overview / Memories
  / Trajectories / Q&A History / Settings. URL-hash persistence (`#tab=…`),
  keyboard shortcuts `1`..`5`, ARIA-labelled tab buttons.
- **Context-aware inspector widgets** (`v19.0.0a3`) — per-page widgets:
  KPI summary + activity feed (dashboard), metadata + budget gauges
  (project), stats summary (network), in-flight + recent traces
  (dispatcher).
- **Quick Ask card on dashboard** (`v19.0.0a5`) — project picker +
  question input at the very top of the main column. Navigates to
  `/projects/<name>?q=<question>` (uses the existing `?q=` pre-fill from
  `v11.0.0a4`) instead of duplicating SSE plumbing.
- **2-column card grid** dashboard layout (`v19.0.0a5`) — Recent Activity,
  FleetQ Bridge, Plugins, Auto-reembed, Recall Q&A History, Project Graph
  arranged as cards (full-width for wide widgets via `md:col-span-2`).
- **SSE-driven activity feed in inspector** (`v19.0.0a7`) — live indicator
  pulse on new events, 1-second DOM-update throttle, last 10 events shown,
  `view all →` deep-link to `/network`.
- **Full memories editor on the Memories tab** (`v19.0.0a8`/`a9`) —
  split-pane layout (file list + textarea + live preview), toolbar with
  Save / Undo / Redo / `diff vs:` revision selector. Renders correctly
  after the `a9` hotfix.
- **Migration script** `scripts/migrate_v19a4_violet_compact.py` —
  committed for traceability of the 359 token+density substitutions.

### Changed
- **Linear-violet OKLCH palette** (`v19.0.0a4`) — accent hue 290 (violet)
  replaces the v8-era cyan. Fresh semantic tokens: `accent` /
  `accent-strong`, `surface-0/1/2/3`, `border-subtle/default/strong`,
  `foreground` / `foreground-muted` / `foreground-dim`. Compiled
  `tailwind.css` grew from ~37 KB to ~42 KB.
- **Compact density pass** (`v19.0.0a4`) — global sweep:
  `gap-4 → gap-2`, `p-4 → p-2.5`, `text-base → text-sm`, `mb-6 → mb-4`,
  `rounded-lg → rounded-md`, sidebar rows tightened to `h-7`.
- **`accent-strong` bumped** from spec `oklch(54% 0.21 290)` to
  `oklch(62% 0.22 290)` to clear `test_dark_mode_pairs_meet_wcag_aa`
  (3.4:1 → ≥ 4.5:1 on `surface-1`/`surface-2`).
- **`x-data` mounting pattern** (`v19.0.0a9` hotfix) — switched from
  `x-data="factory({{ var | tojson }})"` (which collided with
  attribute double-quotes and broke Alpine mounting) to
  `x-data="factory('{{ var | e }}')"`. Same anti-pattern flagged in
  `trajectoryList` for v20.0.0a1 follow-up.
- **Tab buttons** carry `aria-label="<label> tab (shortcut <N>)"` so the
  a11y auditor sees an accessible name even though `x-text` is opaque.
- **`trajectoryList`** relocated under the Trajectories tab (`v19.0.0a2`);
  pre-v19 standalone render is gone.
- **Memories tab** on project page is now the canonical edit surface;
  the legacy `memoriesPanel` block is wrapped in `{% if false %}` and
  no longer emitted (kept inert as artefact for one release).
- **Docs sweep**: README rewritten to reflect v9–v19 reality (dashboard,
  network graph, dispatcher trace, memories editor, budget triad,
  light/dark theme). CHANGELOG created from scratch by mining the
  GA retros. Obsolete v2.x roadmap docs moved to `docs/legacy/`.

### Fixed
- **Memories editor failed to render in `v19.0.0a8`** — the `tojson`-
  inside-attribute pattern collided with HTML attribute parsing,
  Alpine mounted with empty data, and the editor stayed blank. Hotfixed
  in `v19.0.0a9` by switching to single-quoted `'{{ … | e }}'`. The
  same bug was discovered in `trajectoryList` and queued for
  `v20.0.0a1`.

### Removed
- **v10 fixed-footer + v9 mobile hamburger / rail-collapse** patterns
  (superseded by the inspector-collapse model).
- **Topbar nav links** (intentionally retired — Cmd-K palette is the
  single navigation surface).
- **v19.0.0a2 placeholder banner** ("Memories editor — full
  implementation lands in v19.0.0a6") — replaced by the working
  editor in `a8`/`a9`.

### Notes
- **Anti-slop protocol** worked: every alpha required a Playwright
  screenshot to disk before commit. The screenshot for `v19.0.0a8`
  showed an empty Memories tab → the `a9` hotfix shipped within the
  same day. Without the protocol, this would have been a
  "shipped but invisible" repeat of the `v10.a5/a6` over-report.
- **Parallel agent coordination** — three agents (`a5` dashboard, `a6`
  memories, `a7` SSE feed) shipped concurrently. Disjoint scope by
  file (`dashboard.html` vs `project_detail.html` vs inspector block)
  + version-bump coordination via `git pull origin main` before each
  bump worked cleanly. Documented in
  [`docs/sprint-retro-harbormaster-v19.0.0.md`](docs/sprint-retro-harbormaster-v19.0.0.md).
- **Git hygiene pass** (concurrent with v19) — pre-cleanup branch state
  (~110 stale `feat/v(3-18).0-*` branches + 4 `ship/v(N).0.0-ga` +
  2 `fix/v6.0.x-*` + 13 stale worktrees + phantom `parent/`+`worktree/`
  remote refs) reduced to 3 local + 2 remote branches. Tags untouched.

---

## [19.0.0a2] - 2026-05-10

**Theme:** Phase 2 of the v19.0 workspace redesign — five-tab system on
the project_detail page, with URL-hash persistence and 1-5 keyboard
shortcuts. Sets the structural shape that v19.0.0a3-a6 fill in.

### Added
- Five-tab system on `/projects/<name>`: **Overview** / **Memories** /
  **Trajectories** / **Q&A History** / **Settings**. Tab strip carries
  a stable `id="hm-project-tabs"` for e2e tests + CSS.
- URL-hash persistence: `#tab=<id>` survives reload (read on init via
  `restoreFromHash`, written via `replaceState` so the back button
  stays bound to navigation rather than tab toggling).
- Keyboard shortcuts: `1`..`5` map to tab indices. Skips when typing
  in `INPUT` / `TEXTAREA` / `contentEditable`, and when modifier keys
  are held (those gestures belong to Cmd-K / browser tab switching).
- New `tests/ui/test_v19_project_tabs.py` (9 tests).
- Tab buttons carry `aria-label="<label> tab (shortcut <N>)"` so the
  a11y auditor sees an accessible name even though `x-text` is opaque.

### Changed
- `trajectoryList` relocated under the **Trajectories** tab (only one
  instance; pre-v19 standalone render is gone).
- Existing `memoriesPanel` viewer / editor preserved underneath the
  Memories tab placeholder so edit / diff / history flows keep working
  until v19.0.0a6's redesign lands.

---

## [19.0.0a1] - 2026-05-10

**Theme:** Three-column workspace shell — sticky topbar / collapsible
sidebar / fluid main / collapsible inspector. Retires the v10 fixed-footer
and v9 mobile-hamburger / rail-collapse patterns in favour of an
inspector-collapse model with localStorage persistence.

### Added
- New `tests/ui/test_v19_three_column_shell.py` browser test asserts
  landmark visibility (`hm-topbar`, `hm-sidebar`, `hm-main`, `inspector`),
  inspector collapse via the in-pane `«` button, and reload persistence.

### Changed
- App shell rewritten to a four-landmark CSS grid. Sidebar markup moved
  into a partial.
- Dispatcher reachability moved off the topbar nav and onto the Cmd-K
  command palette (`id: 'dispatcher'`, `href: '/dispatcher'`).
- Tests for sidebar, ignored-projects endpoint, app-shell layout, and
  dispatcher-trace endpoint updated for the new contract.

### Removed
- v10 `top-12 bottom-7` fixed-footer pattern.
- v9 mobile hamburger + rail-collapse (superseded by inspector-collapse).
- Topbar nav links (intentionally retired — palette is the single
  navigation surface now).

---

## [18.0.0] - 2026-05-10

**Theme:** Chain close. The autonomous chain across v9 → v18 ships its
final two carry-overs and seals the era. 10 majors, 58 alpha tags, 10 GA
tags in one continuous chain.

### Added
- `v18.0.0a1` — Re-land screenshot autobootstrap CI workflow (closes the
  4-version-old token-scope block from v14 carry-over #1). PNG baselines
  for dashboard / dispatcher / fan_out / project_detail are regenerated
  in CI and committed back to the branch on drift.
- `v18.0.0a2` — Trace waterfall hover / focus tooltip (final cosmetic
  polish from the v17 candidate list). Span attributes surface on hover
  rather than click-to-expand.

### Notes
- Cumulative v9→v18 metrics: 10 majors, 58 alphas + 10 GAs = 68
  versioned tags shipped autonomously. Test suite growth across the
  chain documented in [`docs/sprint-retro-harbormaster-v18.0.0.md`](docs/sprint-retro-harbormaster-v18.0.0.md).

---

## [17.0.0] - 2026-05-10

**Theme:** Trace waterfall renderer + Codex backend parity. Closes an
8-version-old carry-over from v9.0.0a3 (the single-row timeline) by
shipping the true parent / child waterfall renderer that consumes the
backend instrumentation slice landed in v16.0.0a6.

### Added
- `v17.0.0a1` — Trace waterfall renderer at `/dispatcher`. Renders
  parent / child span trees from the SSE `span_start` / `span_end` event
  format. Click-to-expand for span attributes.
- `v17.0.0a2` — Codex backend `tool_use` instrumentation parity. Mirrors
  the `claude.py` span-emit pattern so dispatcher trace works for both
  backends.
- `v17.0.0a3` — N-way reembed compare UI with multi-select checkboxes,
  side-by-side, and the v16.0.0a4 sparkline helper integrated.
- `v17.0.0a4` — KPI strip `tightest_cap` hover tooltip — surface polish
  for the v16.a5 per-project budget triad.

---

## [16.0.0] - 2026-05-10

**Theme:** Per-project budget — the third axis of the budget triad —
plus the backend instrumentation slice that v17 will consume.

### Added
- `v16.0.0a1` — Internal quality cluster (autouse `network_log` fixture,
  `cachedGetter` Alpine helper, `_make_parser` markdown helper).
- `v16.0.0a2` — Pre-commit hardening: `pre-commit` in `[dev]`,
  `post_sync_install_hooks.sh`, doc-parity suggested-edit emitter.
- `v16.0.0a3` — Tour wizard hardening (`data-tour-step` markup attrs,
  3-step `/network` tour).
- `v16.0.0a4` — `GET /api/config/diff?format=html` (HtmlDiff side-by-side)
  plus a tiny SVG sparkline helper.
- `v16.0.0a5` — **Per-project daily call budget.** Third axis of the
  budget triad (alongside per-host and per-tool). Tightest-cap-wins
  arithmetic; surfaced via `GET /api/projects/budget?host=…`.
- `v16.0.0a6` — Trace waterfall — backend instrumentation slice.
  `parent_span_id` + `trace_id` + `span_context` on every span. Renderer
  deferred to v17.

---

## [15.0.0] - 2026-05-10

**Theme:** Test infra hygiene + UI carry-over polish. Closes several
backend / UI gaps from v13–v14 in an extension-only sprint (zero new
source files).

### Added
- `v15.0.0a1` — Memory tag UX cluster (block-list YAML + chip editor +
  AND/OR filter + persistent undo cursor).
- `v15.0.0a2` — Cross-host extensions (concurrent multi-host plugin
  discovery + cross-host config diff).
- `v15.0.0a3` — Live-refresh polish (SSE-driven timeline + dropdown
  live-add).
- `v15.0.0a4` — **N-way reembed comparison** + **per-tool daily call
  budget** (second axis of the budget triad). `GET /api/tools/budget`.
- `v15.0.0a5` — Pre-commit hook integration (`harbormaster-config-check`
  + `harbormaster-config-doc-parity`).
- `v15.0.0a6` — Per-project markdown config + dashboard tour wizard.

---

## [14.0.0] - 2026-05-10

**Theme:** CI workflow + memory polish. The screenshot autobootstrap CI
side was reverted (workflow-scope token block) and closed later in v18.

### Added
- `v14.0.0a1` — Screenshot autobootstrap (deviation — reverted, re-landed
  in v18.a1) + `wt-merge.sh --dry-run`.
- `v14.0.0a2` — `harbormaster-mcp config check` CLI + auto-derived
  network source dropdown.
- `v14.0.0a3` — HTML diff toggle + reembed-row diff button.
- `v14.0.0a4` — **Per-host daily call budget** (first axis of the budget
  triad). `GET /api/hosts/budget` + dashboard KPI strip integration.
  Network event timeline UI.
- `v14.0.0a5` — Memory tagging UI + Cmd+Z revision undo / redo.
- `v14.0.0a6` — Cross-host plugin discovery via SSH.

---

## [13.0.0] - 2026-05-10

**Theme:** Quality + screenshot-diff harness arrival.

### Added
- `v13.0.0a1` — Screenshot-diff harness (Playwright fixtures).
- `v13.0.0a2` — Tailwind v4 utility-class migration (final OKLCH token
  rollover).
- `v13.0.0a3` — Side-by-side HTML diff + reembed diff parity.
- `v13.0.0a4` — Network event filtering (server + UI + URL state).
- `v13.0.0a5` — Smoke bundle (theme reload + nginx + contrast).
- `v13.0.0a6` — **Operator config doc consolidation** —
  [`docs/operator-config-reference.md`](docs/operator-config-reference.md)
  canonical reference for every TOML section.

---

## [12.0.0] - 2026-05-10

**Theme:** Codex backend parity + retention + auth polish.

### Added
- `v12.0.0a1` — **Codex backend token instrumentation.** Real backend-
  reported token usage from the Codex CLI on the SSE `usage` event.
  Pattern: `StreamUsage` + `_StreamWithUsage` lifted to `backends/base.py`
  and re-exported.
- `v12.0.0a2` — Complete `stateBadge` migration (status + reembed + tier).
- `v12.0.0a3` — Operator-configurable retention caps `[retention]`.
- `v12.0.0a4` — Memory revision diff endpoint + bleach extension.
- `v12.0.0a5` — Network stats by-source + `wt-merge.sh` helper.
- `v12.0.0a6` — Cookie-backed bearer for SSE auth (UI doesn't have to
  pass `Authorization:` from JS).
- `v12.0.0a7` — **Light-mode toggle** (auto / light / dark). OKLCH
  semantic colour tokens; no flash on reload.

---

## [11.0.0] - 2026-05-10

**Theme:** Persistence + revisions + sanitised markdown.

### Added
- `v11.0.0a1` — **Persistent SQLite-backed network log** + caller
  propagation. `X-Caller-Project` header threads through MCP calls so
  the network graph survives restarts.
- `v11.0.0a2` — **Per-file memory revision history** (last 20 per file).
  New `~/.harbormaster/memory_revisions.db`; editor `History` toggle.
- `v11.0.0a3` — Bleach-sanitised markdown rendering + live preview pane.
  `markdown-it-py` added to `[ui]`; split-pane editor with 300 ms debounce.
- `v11.0.0a4` — Unified `stateBadge` helper + `?q=` URL pre-fill on
  `askForm`. Cmd-K shareable URLs work.
- `v11.0.0a5` — **Real backend-reported token usage** in the SSE `usage`
  event. Closes the v9.0.0a5 deviation; drops `approximate: true`.
- `v11.0.0a6` — Caches consolidation: ignored TTL + chatOrder cache +
  `GET /api/network/stats?window=` aggregate endpoint.
- `v11.0.0a7` — Async click-handler audit + per-surface SSE heartbeat
  tuning (5 s streaming / 30 s network / 10 s trace).

### Changed
- New top-level config keys: `heartbeat_interval_streaming_s`,
  `heartbeat_interval_network_s`, `heartbeat_interval_trace_s`.

---

## [10.0.0] - 2026-05-10

**Theme:** Memory editor + inter-project network graph + app-shell layout.

### Added
- `v10.0.0a1` — Fix: record streamed Q&A so the dashboard / fan-out /
  project-detail "Recent Q&A" section populates.
- `v10.0.0a3` — **Full app-shell layout** (fixed topbar / sidebar) +
  topbar nav cleanup (drop `/api/projects`, `/api/health` links).
- `v10.0.0a4` — **`[ignore].patterns`** config section + sidebar
  indicator + `GET /api/ignored-projects`.
- `v10.0.0a5` — **Per-project memories viewer** (read-only). Vendored
  `marked.js` v12.0.2 (35 KB).
- `v10.0.0a6` — **Memories editor** (`PUT` / `POST` atomic write-back).
  Allowlisted to `CLAUDE.md` + `.serena/memories/*.md`.
- `v10.0.0a7` — **Inter-project network graph** (Cytoscape vendored,
  373 KB). New `MCPCallLog` ring buffer.
- `v10.0.0a8` — Network chat-list view + view-toggle persistence
  (localStorage-backed view preference).

### Removed
- `v10.0.0a2` — **BREAKING:** legacy `chunk` SSE event removed
  (deprecated v9.0.0a5; one-version deprecation cycle complete).

---

## [9.0.0] - 2026-05-10

**Theme:** Architectural moves — dispatcher trace surface + typed SSE
events + Tailwind v4 vendor. First major in the autonomous chain.

### Added
- `v9.0.0a1` — **Tailwind v4 vendor + wheel-build hook.** Compiles CSS
  at wheel-build time (`build_tailwind_css.py`); wheel ships with the
  minified output. Closes the v8.a7 deferral.
- `v9.0.0a2` — `GET /api/dispatcher/status` real endpoint +
  `dispatcher --url` flag. `DispatcherStats` singleton records per-tool
  counters + in-flight spans.
- `v9.0.0a3` — **Trace waterfall surface** at `/dispatcher`. Single-row
  timeline (parent / child upgrade deferred to v17).
  `GET /api/dispatcher/trace` SSE stream.
- `v9.0.0a4` — SSE Last-Event-ID resumption + per-event id assignment.
- `v9.0.0a5` — **Typed SSE events** (`token`, `usage`) alongside legacy
  `chunk`. Dual-emit migration pattern; `chunk` removed in v10.0.0a2.
- `v9.0.0a6` — Sidebar polish (archived + rail-collapse + host filter) +
  Cmd-K palette dynamic-action.

---

## [8.0.0] - 2026-05-10

**Theme:** Accessibility floor + Cmd-K palette + KPI strip + sidebar.
The v8 line set the "audit-test-per-phase" architectural backbone that
shipped every subsequent major.

### Added
- `v8.0.0a1` — A11y floor: `aria-label` / `aria-live` / `aria-busy` +
  `focus-visible` rings across every interactive surface.
- `v8.0.0a2` — State badges gain icon glyph + full `aria-label`.
- `v8.0.0a3` — Canonical 3-part empty states across 5 surfaces.
- `v8.0.0a4` — **Cmd-K command palette** with bigram fuzzy match.
- `v8.0.0a5` — **KPI strip atop dashboard** + `GET /api/kpi` aggregator.
- `v8.0.0a6` — **Left navigation sidebar** with grouped projects + pinned.
- `v8.0.0a7` — **HTMX dropped**; semantic OKLCH colour tokens added
  (theme migration foundation).

---

## [7.0.0] - 2026-05-09

**Theme:** Regression guards for the v6 graph bug class + operator
control over reembed runs + dashboard polish.

### Added
- `v7.0.0a1` — Browser SVG-render assertion (Playwright bbox check).
- `v7.0.0a2` — Static template safety audit (`html.parser` walk +
  ALLOWLIST).
- `v7.0.0a3` — **Cancel-running-reembed button** + cooperative cancel
  flag.
- `v7.0.0a4` — **Rolling reembed run-history log** + UI table.
- `v7.0.0a5` — `--json` output for `harbormaster-mcp dispatcher status`.
- `v7.0.0a6` — **Language badge** on dashboard cards + `ProjectsCache`
  TTL memo.

---

## [6.0.0] - 2026-05-09

**Theme:** Operations polish — manual reembed trigger, sort / group,
keyboard shortcut help, dispatcher CLI.

### Added
- `v6.0.0a1` — **Manual reembed trigger** + ETA estimation.
  `POST /api/history/reembed` + "run now" dashboard button.
- `v6.0.0a2` — Optimistic-trajectory escalation tier + threshold.
- `v6.0.0a3` — Dashboard sort + group controls.
- `v6.0.0a4` — Keyboard shortcut help popover.
- `v6.0.0a5` — Streaming-chunks dispatcher stress test.
- `v6.0.0a6` — **`harbormaster-mcp dispatcher status` CLI** (new source
  file `dispatcher_cli.py`).

---

## [5.0.0] - 2026-05-09

**Theme:** Operational visibility — auto-reembed UI, per-tool thread
safety, optimistic-trajectory polish, dashboard filter.

### Added
- `v5.0.0a1` — **Auto-reembed UI panel** consuming `/api/history/state`.
  Phase badge + progress bar + current host + last-error live; auto-poll
  3 s.
- `v5.0.0a2` — Backend-tools stress via fake-claude harness.
- `v5.0.0a3` — Per-tool thread-safety map (selective opt-in for the
  dispatcher pool).
- `v5.0.0a4` — Optimistic trajectory polish (cross-fade + writeback
  spinner).
- `v5.0.0a5` — Graph zoom UX polish (keyboard shortcuts + double-tap).
- `v5.0.0a6` — Dashboard project filter + URL state.

---

## [4.0.0] - 2026-05-09

**Theme:** Test coverage hardening + auto-reembed + UI polish + dispatcher
pool.

### Added
- `v4.0.0a1` — Real-world lockfile fixtures (pnpm v6 / v9 / yarn v1 / yarn
  berry) + expanded Playwright.
- `v4.0.0a2` — URL state on `/api/recall` + copy-link affordance.
- `v4.0.0a3` — Graph pinch-zoom + drag-pan.
- `v4.0.0a4` — Optimistic trajectory insert.
- `v4.0.0a5` — **Auto-reembed on drift detection.** `/api/history/state`
  exposes phase + progress.
- `v4.0.0a6` — **Multi-worker dispatcher pool** (FleetQ side).

---

## [3.0.0] - 2026-05-09

**Theme:** Closes every loop the v2 retro list flagged as a v3
candidate, plus the testing scaffolding the v2.1 UI deserved. Single
monolithic alpha line (a1–a10).

### Added
- `v3.0.0a1` — **`agent.request` → MCP dispatcher** wiring on the FleetQ
  side. Single-thread dispatch from a queue.
- `v3.0.0a2` — Live bridge runtime state in `/api/bridge/status`.
- `v3.0.0a3` — `pnpm-lock` + `yarn.lock` parsers for project graph.
- `v3.0.0a4` — **Parallel cross-host recall** via thread pool.
- `v3.0.0a5` — Pysher worker-thread offloading (FleetQ pub/sub).
- `v3.0.0a6` — Bearer-token plumbing for SSE forms.
- `v3.0.0a7` — Inline ask form on dashboard cards.
- `v3.0.0a8` — Cross-section trajectory refresh events.
- `v3.0.0a9` — Mobile-friendly graph + URL state encoding.
- `v3.0.0a10` — Headless browser tests via Playwright.

### Notes
- Test suite delta: 554 → 621 (+67 unit tests + 7 browser smoke).
- 9 CI jobs per push (was 8 at v2.1.0; `smoke-ui-browser` added).

---

## [2.1.0] - 2026-05-09

**Theme:** Local operator console arrives. The dashboard becomes a usable
shell for Harbormaster's tools.

### Added
- `v2.1.0a1` — **Mermaid project graph** + FleetQ Bridge / plugin status
  panels on the dashboard.
- `v2.1.0a2` — Per-project detail page (`/projects/<name>`).
- `v2.1.0a3` — Recall search inline.
- `v2.1.0a4` — "Ask this project" SSE form.
- `v2.1.0a5` — Delegate + fan-out forms.
- `v2.1.0a6` — Trajectory history view.

---

## [2.0.1] - 2026-05-09

### Fixed
- SSH argv-quoting bug.
- Pysher kwarg incompat.
- Plugin warn-missing fallthrough.

### Added
- `plugins list` CLI.

---

## [2.0.0] - 2026-05-09

**Theme:** Lockfile-aware deps + transitive graph + multi-backend + plugin
API + cross-host recall + per-token streaming through the Bridge.
Widened existing tools rather than adding new ones.

### Added
- Lockfile-aware deps + transitive graph (`project_graph` gains
  `transitive: bool = False`).
- Embedding upgrade-in-place migration path.
- **Multi-backend (Codex).** Backend abstraction lifted to a Protocol;
  all `ask_*` / `delegate_*` paths route through
  `get_backend_for_project()`.
- Plugin API.
- LLM-driven triple extraction for the FleetQ KnowledgeGraph.
- Cross-host recall aggregation (`recall_qa` gains `host="all"` mode).
- Per-token streaming through the FleetQ Bridge.

### Notes
- 7 alpha tags + GA. 115 new unit tests (392 → 507 + 1 skip).
- Zero breaking changes — every v2 feature is opt-in via config.

---

## [1.0.0] - 2026-05-09

**Theme:** Drop the alpha suffix after 20 alpha tags (v0.1.1 + a1 → a20).
All four v1.2 phases shipped this session.

### Added
- **8 MCP tools** — `list_projects`, `list_hosts`, `project_status`,
  `ask_project`, `delegate_task`, `fan_out_ask`, `recall_qa`,
  `project_graph`. All accept optional `host=` for SSH fan-out.
- **Local + SSH** fan-out for every project-targeting tool.
- **Live UI** with PyPI alpha publish pipeline.
- **SSE chunk streaming** on both sides (Harbormaster → MCP client
  and Bridge → FleetQ).
- **FleetQ Bridge HTTP-tunnel mode (Path C)** — register / heartbeat /
  disconnect.
- **v1.1**: Platform Tool seeder · A2A Agent Card per project · live
  FleetQ smoke · `update_endpoints` watch · Memory writeback · operator
  guide.
- **v1.2**:
  - **Q&A history** with sqlite-vec + fastembed (`recall_qa`).
    `~/.harbormaster/qa.db` (per-host db) — `qa_log` + `qa_vec` (384-dim
    bge-small) + `qa_fts5` fallback.
  - **Auto project graph** from manifest parsing (`project_graph`).
    No LLM, no network — pure file parsing on a per-process in-memory
    cache, refreshed on manifest mtime.
  - **Federated KnowledgeGraph via FleetQ** — heuristic triple
    extraction (mentions / uses / exposes) with `[fleetq]
    kg_max_triples_per_call` cap.
  - **Cross-session memory recall via auto-grounding** — top-K matches
    silently prepended to the `claude -p` prompt when `recall_qa`
    finds matches above threshold.

### Notes
- 20 alpha tags + 1 GA tag.
- MIT licensed; published on PyPI as `harbormaster-mcp` via Trusted
  Publishing (OIDC).
- Lineage: grew out of `project-router-mcp` v0.1 (2026-05-08).

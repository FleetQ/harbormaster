# Sprint Retro — Harbormaster v19.0.0a3

**Date:** 2026-05-10
**Theme:** Phase 3 of the v19.0 workspace redesign — context-aware
widgets in the right inspector pane. Replaces the static a1
placeholder with per-page Alpine factories that pull live data from
existing API endpoints.

## What shipped

- `base.html` exposes a new `{% block inspector %}` hook inside the
  `#inspector` aside. Default placeholder text ("No inspector widgets
  for this page.") shows when a page declines to override; every page
  template added in v19 now overrides.
- **Dashboard inspector** (`dashboard.html`):
  - `kpiInspector()` Alpine factory mirrors the four headline KPI
    numbers (Projects / Active embeds / 1h queries / Bridge) in a
    compact 2-column `<dl>`. Polls `/api/kpi` every 10s.
  - `activityFeed()` Alpine factory tails the last 10 MCP-call events
    via `/api/network/events?limit=10`. Renders `time + tool + target`
    per row, soft-fails to "no recent calls" when empty.
- **Project detail inspector** (`project_detail.html`):
  - `projectInspector()` factory hydrates METADATA from the page's
    own `project` template context (`last_commit.hash`, `language`,
    `path`, `has_serena`, `has_claude_md`) — no extra round-trip on
    first paint.
  - BUDGET (24H) section calls `/api/projects/budget?host=<host>`,
    narrows the response to this project's row, surfaces
    `calls_24h / budget`, `usage_pct`, and the `tightest_cap_axis`
    so the operator can spot the binding constraint at a glance.
  - 404 from the budget endpoint (host not in `[hosts.*]`) renders
    a `host not in [hosts.*]` hint instead of crashing the panel.
- **Network inspector** (`network.html`):
  - `networkInspector()` factory pinned to `?window=1h` so the
    inspector stays consistent independent of the main panel's
    window selector. Surfaces `total_calls`, `error_rate`, the full
    `by_tool` map, and the top-5 `top_projects_by_calls`.
  - The full 5-column stats grid + filter controls stay in the main
    column where they have room — pragmatic call per spec.
- **Dispatcher inspector** (`dispatcher_trace.html`):
  - `dispatcherInspector()` factory polls `/api/dispatcher/status`
    every 5s. Surfaces `active_workers`, `queue_depth`, a
    human-friendly `last_dispatched_at` ("never" / "5s ago" /
    "12m ago"), and a per-tool counter row sorted by `in_flight` then
    `total_completed`.
- **Fan-out inspector** (`fan_out.html`):
  - Minimal context help — "About fan-out" blurb + Related links to
    `/dispatcher` and `/network`. Intentionally no data-fetching
    factory; the form already owns the main column.

## Test deltas

- New `tests/ui/test_v19_inspector_content.py` — 15 tests, all
  passing:
  - `base.html` exposes the inspector block hook AND the block
    renders inside the `#inspector` aside (not outside it).
  - All 5 page templates override `{% block inspector %}` and carry
    a stable `data-tour-step="inspector-content"` hook.
  - Dashboard inspector binds `kpiInspector()` + `activityFeed()`
    factories, references the 4 KPI labels, fetches from
    `/api/network/events?limit=10`, and uses `setInterval` for
    auto-refresh.
  - Project inspector renders the 6 metadata fields, fetches
    `/api/projects/budget?host=`, and surfaces `tightest_cap_axis`.
  - Network inspector pinned to `?window=1h` and renders the
    headline + by-tool + top-projects sections.
  - Dispatcher inspector pulls `/api/dispatcher/status` and surfaces
    `active workers / queue depth / last dispatch / By tool`.
  - Fan-out inspector overrides the block exactly once and links
    to `/dispatcher` + `/network`.
  - Token regression guard: every inspector block uses `border-border`
    and forbids `border-muted` / `text-secondary` / `bg-primary`
    (which don't exist in the project's `@theme`). Pin against the
    a2 deviation lesson.
- Test count: 1673 → 1688 (+15).
- All v19 + app-shell + project-tabs UI tests still pass (38 in the
  union suite).
- mypy `--strict` clean (57 source files); ruff clean.
- Pre-existing baseline failures (8 `test_stream_ask_*` order-dependent
  + 16 `test_bridge.py` scope-mismatch) remain; not introduced by
  this work, both documented in the a2 retro.

## Visual verification

4 screenshots at `/tmp/v19-a3-{dashboard,project,network,dispatcher}.png`
(1280x720, captured against the verification UI on port 17799,
operator UI on 17636 untouched throughout).

- **dashboard.png** — right pane shows SUMMARY (Projects 62, Active
  embeds running 0/1, 1h queries 0, Bridge token missing) + RECENT
  ACTIVITY (no recent calls). Tour overlay visible but inspector
  content correctly populated.
- **project.png** (`/projects/agent-fleet`) — METADATA: `last
  commit: 59401ade (today)`, `language: php`, `host: local`, `path:
  /Users/katsarov/htdocs/agent-fleet`, `serena memories: yes`,
  `CLAUDE.md: yes`. BUDGET (24H): `host not in [hosts.*]` (correct
  soft-fail in this dev environment).
- **network.png** — LAST 1H (total calls 0, error rate 0.0%) +
  BY TOOL (no calls in window) + TOP PROJECTS (no projects active).
  All three sections render at first paint with correct empty-state
  copy.
- **dispatcher.png** — IN-FLIGHT (active workers 0, queue depth 0,
  last dispatch never) + BY TOOL (no tool activity yet). Counters
  align with the empty-trace state in the main column.

## Lessons (compounding)

- The spec's reference to `kpi.active_embeds` as a flat field was
  inaccurate — `/api/kpi` actually returns it as
  `{phase, processed, total}`. Caught while wiring the dashboard
  inspector; an `embedsLabel()` helper now formats `phase
  processed/total` (e.g. `running 0/1`) instead of letting Alpine
  render `[object Object]`.
- The spec's project-metadata sketch used `last_commit.sha` —
  ProjectInfo's git probe actually keys it as `last_commit.hash`
  (since `_git_last_commit` uses `%h`). The first screenshot showed
  `last commit: —` because of the field-name mismatch; fixed to
  fall back through `c.hash || c.sha` and re-screenshotted to
  confirm `59401ade (today)`.
- The spec's budget example assumed a per-host/per-tool/per-project
  JSON shape that doesn't match `/api/projects/budget`'s actual
  output (`{host, window_hours, projects: [{project, calls_24h,
  budget, usage_pct, tightest_cap, tightest_cap_axis}]}`). The
  inspector now narrows to the matching `projects[]` row by name
  and surfaces the tightest-cap axis explicitly. Lesson: read the
  endpoint's actual response shape before mapping, not the spec's
  sketch.
- Tailwind v4 token guard pulled forward from a2: a parametrized
  test asserts every inspector block uses `border-border` and
  forbids `border-muted` / `text-secondary` / `bg-primary`. Cheap
  pin against future spec drift.
- `wait_until="networkidle"` on `/network` and `/dispatcher` times
  out because both pages hold open SSE streams (network event
  stream + dispatcher trace stream). Screenshot still captures
  successfully because the page DOM is rendered before the SSE
  handshake; the timeout exception is logged but non-fatal.

## Next

- v19.0.0a4: per-project budget edit controls in the Settings tab
  (the `<dl>` shape from a2 already accommodates them) — plus
  surface the budget figures from a3's project inspector as
  inline-editable fields.

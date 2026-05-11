# Sprint Retro — harbormaster v21.0.0a7

**Tag:** `v21.0.0a7`
**Phase:** 7 of 10 (v21.0 polish sprint)
**Date:** 2026-05-11
**Theme:** KPI sparklines wiring + final a11y polish pass

## What shipped

### 1. `GET /api/kpi/history`

A new read-only endpoint at `src/harbormaster/ui/routes.py` returning
24 hourly buckets (oldest → newest) for each numeric KPI cell:

```jsonc
{
  "projects":        [int, ... × 24],   // stable count repeated
  "active_embeds":   [0,   ... × 24],   // placeholder until history persists
  "recent_queries":  [int, ... × 24],   // COUNT-per-hour against network_log
  "host_budget":     [0,   ... × 24],   // placeholder until budget history persists
}
```

The only non-trivial work is the per-hour `COUNT(*) FROM mcp_calls
WHERE timestamp BETWEEN …` against the network_log SQLite store —
the covering index on `timestamp` (epoch-ms) keeps each scan cheap.
Soft-fails per series: a missing `[history]` extra or empty log just
returns `[0]*24` so the SVG still renders a flat baseline rather
than a broken cell.

### 2. KPI strip sparkline wiring (dashboard)

Each numeric KPI cell now carries a `data-kpi-sparkline="<id>"` slot
beneath the value. The `kpiStrip()` Alpine factory grew:

- `history` (4-key object of 24-int arrays)
- `historyVersion` (reactive counter — bumped after each successful
  fetch so `x-html` re-evaluates reliably)
- `loadHistory()` — single `/api/kpi/history` round-trip
- `historySparkline(key)` — delegates to the v16.0.0a4 global
  `window.sparklineHtml(...)` helper

`x-init` now reads `loadKpi(); loadBudget(); loadHistory(); startPolling()`
and `startPolling()` keeps the history series fresh every 30s alongside
the existing KPI poll.

Bridge + Dispatcher cells are intentionally left without sparklines
— their values are coarse pill states ("token missing" / "ready"),
not numeric time series.

### 3. Budget gauge sparkline (project inspector)

`src/harbormaster/ui/templates/project_detail.html` now pulls
`/api/kpi/history` from `projectInspector()` and renders a 160×22
filled-area sparkline beneath the Budget block — but ONLY when at
least one bucket in the `recent_queries` series is non-zero. A fresh
install with no traffic stays visually quiet; an active host shows
a 24h usage line.

### 4. Final a11y polish pass

**Audit-driven floor (now enforced via tests):**

- **`focus-visible:ring-2 focus-visible:ring-accent` on every
  `<button>`** — 29 violations across 5 templates were auto-fixed
  (base 3, dispatcher_trace 2, network 3, dashboard 11,
  project_detail 10). `test_every_button_has_focus_visible()`
  now asserts the floor.
- **`aria-label` floor for icon-only buttons** — all glyph-only
  buttons (☰ / ⓘ / ◐ / « / » / ×) already carried `aria-label`.
  `test_every_button_has_aria_label_or_visible_text()` strips
  `aria-hidden="true"` spans before deciding whether a button has
  a visible accessible name.
- **`title` fallback** added to base.html's hamburger, info,
  inspector collapse «, inspector expand », and cheatsheet × —
  hover tooltip + extra screen-reader fallback.
- **`role="tabpanel"`** on every tab-content section across pages
  that use the v21.0.0a6 `_tabs.html` partial. `network.html` was
  the one gap (stats panel + events panel) — both now annotated
  with `role="tabpanel"` and an `aria-label`.
- **`<html lang="en">`** verified — already present in base.html
  (untouched), test pinned.

### 5. SSE auto-reconnect verification

The existing `test_sse_last_event_id.py` suite (7 tests) covers
the `Last-Event-ID` replay contract end-to-end — they all pass.
Manual verification on port 17799 confirmed the activity feed
EventSource transparently reconnects when the UI process restarts,
no manual reload required (the browser's native EventSource
retry-after-1s machinery does the heavy lifting; our `id:` field
on every chunk + `usage` + `result` event lets the server pick up
from the right offset).

## Code metrics

- **Test count delta:** +10 (1813 → 1823 in `tests/`, excluding
  pre-existing test_bridge.py fixture-scope failures and Playwright
  3-column-shell flakes — both identical on `main`)
- **Files modified:**
  - `src/harbormaster/__init__.py` (version bump)
  - `src/harbormaster/ui/routes.py` (+71 lines: `/api/kpi/history`)
  - `src/harbormaster/ui/templates/dashboard.html` (KPI strip sparkline
    wiring + Alpine factory growth)
  - `src/harbormaster/ui/templates/project_detail.html` (budget gauge
    sparkline + `loadHistory()` in `projectInspector`)
  - `src/harbormaster/ui/templates/base.html` (3 buttons:
    title fallbacks + focus-visible adds)
  - `src/harbormaster/ui/templates/network.html` (2 buttons +
    2 tabpanel role annotations)
  - `src/harbormaster/ui/templates/dispatcher_trace.html` (2 buttons)
  - `tests/ui/test_v21_sparklines_and_a11y.py` (new, 10 tests)
  - `docs/sprint-retro-harbormaster-v21.0.0a7.md` (this file)
- **A11y audit floor counts:** 29 focus-visible classes added; 5
  title fallbacks added; 2 tabpanel roles added.

## Visual verification

`/tmp/v21-a7-dashboard-sparklines.png` + `/tmp/v21-a7-kpi-strip-only.png`
captured with Playwright on `127.0.0.1:17799` (operator on 17636
untouched). KPI strip shows 4 sparkline cells rendering valid SVG
(Projects = flat 62, Active embeds / Recent queries / Host budget =
flat zero baseline as expected on a quiet local dev instance).

## Lessons

### EventSource reconnect = browser-native + monotonic `id:` on every event

We did not need to write reconnect-side glue. The v15.0.0a6 invariant
("emit `id: <monotonic-int>`  on every SSE event") plus the v15-era
`Last-Event-ID` replay endpoint contract is enough for the
browser's built-in `EventSource` retry to seamlessly resume.

### Alpine `x-html` reactivity: scalar > object reassignment

First attempt mutated `this.history[k] = body[k]` per key + bumped
`historyVersion`. Alpine 3's proxy DID pick up the mutation, but the
`x-html` binding occasionally captured a stale closure value. Adding
`const _v = this.historyVersion; void _v;` at the top of
`historySparkline()` to explicitly read the version scalar made the
DOM re-render deterministically — Alpine's effect system reliably
tracks scalar property reads.

### Reactive timing in Playwright tests = use `wait_for_function`

Visual verification originally used `time.sleep(N)`. The
`primeAuthCookie() → fetch /api/auth/cookie → x-init → loadHistory()
→ x-html re-eval → DOM rerender` chain took 5–6 seconds on a quiet
local. `page.wait_for_function("document.querySelectorAll(...).length
>= 4", timeout=10000)` is the right tool, not `sleep`. Pinning this
in the screenshot tooling so future phases get reliable visual
diffing.

### A11y audit floors are cheap once spec'd

The 29 missing `focus-visible:` classes were applied in a single
Python regex pass — no per-file babysitting. The audit-style tests
(`test_every_button_has_focus_visible()`) now enforce the floor for
future phases, so this regression class is closed.

## Carry-over to Phase 8

- Host budget + active embeds history series still return `[0]*24`
  — when v21.0.0a8+ persists those time series, the sparklines come
  alive without any frontend change (the endpoint shape already
  matches).
- A subset of pre-existing failures (`test_v19_three_column_shell.py`
  Playwright 3-column-shell tests + `test_bridge.py` fixture-scope
  errors) are unrelated to this phase and remain as-is for the
  Phase 8 / 9 cleanup pass.

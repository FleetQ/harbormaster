# Sprint Retro — Harbormaster v8.0.0a5

**Date:** 2026-05-10
**Theme:** Phase 5 of the v8 UI polish line — at-a-glance KPI strip
atop the dashboard. Five glanceable metrics (Projects, Active
embeds, Recent queries 1h, Bridge, Dispatcher) in a single
horizontal grid that auto-refreshes every 30s. New backend
aggregator endpoint `/api/kpi` packs the metrics into one
round-trip so the UI doesn't fan out 5 polls.

## What landed

### `harbormaster` (this repo)

| SHA | Subject |
|-----|---------|
| (merge) | feat(ui): KPI strip atop dashboard with /api/kpi aggregator endpoint |

## Capabilities (this sprint)

### 1 · `/api/kpi` aggregator endpoint

New route in `src/harbormaster/ui/routes.py`. Returns:

```json
{
  "projects": 27,
  "active_embeds": {"phase": "idle", "processed": 0, "total": 0},
  "recent_queries": 14,
  "since_seconds": 3600,
  "bridge": "configured",
  "dispatcher": "ready"
}
```

* `projects` — reuses the v7.0.0a6 `ProjectsCache`. Zero extra
  filesystem walk on warm hits.
* `active_embeds` — reads `read_reembed_state()` (same source as
  `/api/history/state`). Soft-fails when `[history]` extra is
  missing.
* `recent_queries` — single-query covering-index scan via the new
  `QAStore.count_since()` helper. Soft-fails to `null` when
  `[history]` is disabled or the store is unavailable.
* `bridge` — coarse pill state matching the existing bridge badge
  (`disabled` / `token missing` / `configured`). Runtime detail
  stays in `/api/bridge/status`.
* `dispatcher` — placeholder `"ready"` until the v9 trace
  waterfall surface ships (per the v8 phase plan provision).
* `since_seconds` — echoed back; the actual SQL clamps below 60s
  to avoid pathologically tight scans.

### 2 · `QAStore.count_since(since_unix_seconds)` helper

New method on the QA store. One SQL row, uses the existing
`created_at` index. Powers the recent-queries KPI without forcing
the UI to fetch + count `/api/trajectories` rows.

```python
def count_since(self, since_unix_seconds: int) -> int:
    row = self._conn.execute(
        "SELECT COUNT(*) AS n FROM qa_log WHERE created_at >= ?",
        (since_unix_seconds,),
    ).fetchone()
    return int(row["n"]) if row else 0
```

### 3 · KPI strip atop dashboard

New `<section x-data="kpiStrip()" x-init="loadKpi(); startPolling()">`
above the existing status strip. Renders 5 cells in a
`grid-cols-2 md:grid-cols-3 lg:grid-cols-5` responsive grid:

* **Projects** — large numeric display + aria-label "N projects
  discovered".
* **Active embeds** — phase label or `processed/total` ratio when
  running. Color-coded per phase (cyan/emerald/rose/amber/gray).
* **Recent queries (1h)** — large numeric display.
* **Bridge** — coarse pill text + matching color class.
* **Dispatcher** — emerald "ready" until v9.

Each cell carries `data-kpi-cell="<id>"` for audit, `:aria-label`
binding for SR, and falls back to `—` when its source returns
`null`/`undefined`.

### 4 · `kpiStrip()` Alpine scope

Single `loadKpi()` fetch + `startPolling()` 30s setInterval.
Per-cell `activeEmbedsLabel()`, `activeEmbedsClass()`,
`bridgeClass()` helpers keep the template presentational. Soft-
fails (catches all errors, leaves `kpi = {}` so cells display `—`)
so a backend hiccup doesn't break the dashboard.

### 5 · Static + endpoint audit (`tests/ui/test_kpi_endpoint.py`)

16 new test parametrisations:

* `test_kpi_endpoint_canonical_shape` — all 6 keys present.
* `test_kpi_projects_count_zero_on_empty` — empty install → 0.
* `test_kpi_active_embeds_shape` — phase / processed / total.
* `test_kpi_recent_queries_null_when_history_disabled`.
* `test_kpi_bridge_disabled_when_fleetq_off`.
* `test_kpi_dispatcher_placeholder_ready`.
* `test_kpi_since_seconds_echoed`.
* `test_kpi_since_seconds_floored_at_60`.
* `test_kpi_cell_present_in_dashboard[*5]` — one per cell.
* `test_kpi_strip_alpine_scope_defined` — `kpiStrip()` + helpers.
* `test_kpi_strip_aria_label_on_section` — section labelled.
* `test_kpi_cells_bind_aria_labels` — every cell binds aria-label.

## Real numbers

- 5/5 v8.0.0a5 sub-items shipped (full Phase 5 plan)
- 1 feature branch merged (no PR)
- +16 new tests (865 → 881 collected; +0 source files, 52 total)
- mypy --strict + ruff: clean (after fixing two type errors:
  `ReembedState.get(...)` → attribute access, and missing
  `api_token` field → `api_token_env` env-var lookup mirroring
  /api/bridge/status)
- Backwards-incompatible changes: 0
- Templates touched: 1 / 5 (dashboard.html)

## What worked

- **Aggregator endpoint > 5 fanned-out polls.** One round-trip
  beats five — saves connection overhead and gives the operator
  a consistent timestamp across all 5 cells. Polling cadence is
  the same regardless.
- **Soft-fail per cell, hard-fail nowhere.** Each KPI source
  catches its own ImportError + Exception and falls back to
  `null`. Operators always see *some* numbers; missing extras
  show `—` rather than 500ing the whole strip.
- **Reuse `ProjectsCache` for the count.** Zero new cache logic
  needed; the same memo that protects `/api/projects` also
  protects `/api/kpi`. First-hit warmup, every-30s-poll hits
  cache.
- **Reuse `read_reembed_state()` rather than reading the JSON
  directly.** Same source-of-truth as `/api/history/state` so the
  KPI strip's "running 4/12" exactly matches the larger reembed
  panel below.

## What we'd do differently

- **Skip the noqa on `except (ImportError, Exception)`.** Ruff
  would flag a bare `Exception` catch — the `# noqa` makes that
  explicit but reads like a workaround. Could be cleaner with
  three separate `try` blocks (one per source), each catching
  only the known exception set. Defer; the soft-fail intent is
  documented and the `# noqa` is the canonical escape hatch.
- **Hook the dispatcher cell to a real `/api/dispatcher/status`
  endpoint when the v9 waterfall lands.** Right now it's a hardcoded
  `"ready"`. v9 plan: swap the static string for a real fetch +
  add a "queued / running / drained" state model.

## Action items for the next sprint (v8.0.0a6)

1 · Phase 6 — sidebar with grouped project navigation. 240px
left rail (hidden on mobile, hamburger toggle), persisted
collapsed/expanded state in `localStorage`, project grouping by
**Pinned** (operator-marked) → **Recently asked** (last 5) →
**By language** (Python / TypeScript / etc) → **Archived**, plus
search-within-sidebar fuzzy filter.

## Out-of-scope (still)

- Per-host KPI rollup. v8.0.0a5 only counts queries from the
  local host's QAStore. v9 multi-host roll-up is a natural fit.
- KPI-strip drill-down (click "Recent queries: 14" → opens
  recall panel pre-filled). Defer; the recall panel below is
  one scroll away and not yet a friction surface.
- "Yesterday's count" comparison sparkline. Pure visual polish;
  Phase 7 (Tailwind v4) is the natural moment to add SVG sparks.

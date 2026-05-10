# Sprint Retro — Harbormaster v14.0.0a4

**Date:** 2026-05-10
**Theme:** Two observability surfaces — per-host call budget + network
event-density timeline view.

## What landed

### `harbormaster` (this repo)

| SHA | Subject |
|-----|---------|
| `a5da2c3` | feat(v14.0.0a4): per-host call budget + network event timeline |

## Capabilities (this sprint)

### 1 · Per-host call budget

New optional `daily_call_budget` field on `[hosts.<label>]` config:

```toml
[hosts.alpha]
ssh_host = "alpha.local"
daily_call_budget = 100   # warn-line for fan_out / delegate volume
```

New endpoint `GET /api/hosts/budget` returns:

```json
{
  "window_hours": 24,
  "hosts": [
    {"host": "alpha", "calls_24h": 12, "budget": 100, "usage_pct": 12.0},
    {"host": "beta",  "calls_24h": 0,  "budget": null, "usage_pct": null}
  ]
}
```

Hosts WITHOUT a configured budget still appear (with
`budget = null` / `usage_pct = null`) so the operator gets full
coverage in one place. Targets seen in `network_log` but NOT
configured under `[hosts.*]` are NOT reported — budget is a
per-configured-host concept.

The dashboard KPI strip grows a 6th cell ("Host budget") showing the
worst-utilized configured host's percentage, color-coded:

* `>= 100%` — red (over-budget)
* `>= 80%` — yellow (warn)
* otherwise — green (healthy)
* no budgets configured — `—` (gray)

Implementation note: the count_by_target lookup is on `network_log`
(SQLite, indexed) — much cheaper than opening per-host QAStore DBs
which require an embedding backend just to read.

### 2 · Network event timeline view

The `/network` page header gains a third view button: Graph / Chat /
**Timeline**. Timeline view renders a horizontal-bar event-density
chart over either the last 1h (1-minute buckets, 60 bars) or last
24h (1-hour buckets, 24 bars) — toggle inside the panel.

The chart is **inline SVG** with no new vendored library
(constraint compliance — "vendored only — no new CDN deps"). Each
bar's height is proportional to the event count in that bucket;
hovering surfaces the count via `<title>` attr. Bucket boundaries
align to wall-clock minutes/hours (e.g. for 24h the leftmost bar is
"now − 24h" rounded to the hour).

Bucketing is pure client-side over the same `events` array the chat
view uses — no extra round-trip. The view selection persists in
localStorage like Graph/Chat already did.

## Real numbers

- 2/2 v14.a3 sprint-plan items shipped (host budget + network timeline)
- 1 commit, 7 files changed (1 config, 2 templates, 1 doc, 3 modules
  with related plumbing)
- 14 new tests in `tests/ui/test_v14_host_budget_and_timeline.py`:
  HostConfig schema (3) + count_by_target (2) + /api/hosts/budget (3)
  + timeline UI wiring (5) + KPI cell (1)
- Test suite delta: 1384 → 1398 passed
- Lint: ruff clean. Type-check: `mypy --strict` clean (57 source files)
- Backwards-incompatible changes: 0 (new field is `Optional`,
  defaults to None; new endpoint additive; new view button additive)

## What worked

- **Reusing `network_log` instead of QAStore for the budget query.**
  QAStore's `open()` requires constructing an embedding backend just
  to read row counts, which is prohibitive for a per-poll endpoint.
  network_log gives identical-grain data with zero cold-start cost.
- **Inline SVG over a chart library.** The 60-bar / 24-bar timeline
  is ~10 lines of SVG + an Alpine `:height` binding. Adding e.g.
  Chart.js would have been ~40KB minified for what's effectively
  a `<rect>` loop.
- **Soft-fail on `loadBudget()` so KPI cell shows `—` if endpoint
  500s.** Same pattern as `loadKpi`. Single-cell fallback prevents
  one broken endpoint from breaking the whole strip.

## What to change / next

- **Cross-section coupling for the doc test.** Adding
  `daily_call_budget` required also touching
  `docs/operator-config-reference.md` to keep `test_every_config_field_documented`
  green. Caught the gap immediately on first failing run, but a
  pre-commit hook to fail-loudly when adding a config field
  without a doc edit would be even faster.
- **No SSE-driven refresh on the timeline view.** New events arrive
  via SSE for the chat/graph views, and the timeline shares the
  same `events` array — but the bucket getters only re-run when
  Alpine re-renders, which happens on view toggle. Acceptable for
  v14.a4; revisit if operators report stale density bars during
  long timeline-view sessions.

## Action items for the next sprint (v14.0.0a5)

1. **Memory tagging UI.** Each memory file (CLAUDE.md,
   `.serena/memories/*.md`) can carry YAML frontmatter with
   `tags: [foo, bar]`. UI lists files grouped by tag; tag filter
   input. Tags rendered as pill badges.
2. **Memory editor undo/redo via revision history.** Cmd+Z /
   Cmd+Shift+Z navigate the v11.a2 revision history (load
   previous/next revision into the editor). Saves create new
   revision (existing behavior).

## Out-of-scope (still)

- Per-tool budgets (only per-host; per-tool is YAGNI for now).
- Live SSE-driven timeline refresh (covered above).
- True token / cost accounting against `cost_cents` — would require
  per-host QAStore opens with an embedding backend or a separate
  metrics rollup endpoint. The call-count proxy is good enough for
  the warn-line use case.

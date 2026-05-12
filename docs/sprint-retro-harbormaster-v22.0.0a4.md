# Sprint Retro — Harbormaster v22.0.0a4

**Date:** 2026-05-12
**Theme:** Built the operator-facing UI for async delegated jobs. New
`/jobs` page lists every row from `delegated_jobs` with status-filter
chips, inline expand for full output/error (lazy-fetch per v21.0.8),
and a live counter strip (`queued / running / completed_today /
failed_today`). Three new JSON endpoints back the page; the command
palette gains a "Delegated jobs" entry.

## What landed

| File | Subject |
|---|---|
| `src/harbormaster/ui/routes.py` | `/jobs` HTML + 3 new `/api/delegated-jobs*` JSON endpoints |
| `src/harbormaster/ui/templates/jobs.html` | new — Alpine.js list view with filter chips + expand |
| `src/harbormaster/ui/templates/base.html` | adds `/jobs` to the Cmd-K command palette |
| `tests/unit/test_jobs_ui.py` | 9 endpoint + template-render tests |
| `src/harbormaster/__init__.py` | 22.0.0a3 → 22.0.0a4 |
| `docs/sprint-retro-harbormaster-v22.0.0a4.md` | this file |

## Capabilities

### Endpoints

- `GET /jobs` — HTML page. Filter chips: All / Queued / Running /
  Completed / Failed. Row expand triggers a lazy-fetch of the full
  payload (avoids shipping every job output in the list response).
- `GET /api/delegated-jobs?status=&project=&limit=` — list. Filters
  AND together; ``status`` validated against the schema's status set
  (400 on bogus value). ``limit`` bounded 1..1000.
- `GET /api/delegated-jobs/summary` — counts for the page header.
  Single SQL aggregate, wrapped in `asyncio.to_thread` per v21.0.3
  pattern.
- `GET /api/delegated-jobs/{job_id}` — one row, 404 on unknown. Used
  by the row expand.

### Page UX

- Each row shows project, task (truncated + title-on-hover), inbox
  badge, status badge with `writes` chip if `allow_writes=True`,
  duration, age.
- Expand shows: job_id, cid, model, deliverable, output (in a
  `<details>` block), error (in an error-tinted `<details>` block).
- Counter strip auto-loads on page open; reload button (`↻`) refreshes
  both summary + list manually.
- All buttons carry `aria-label` + `focus-visible:` ring per the
  a11y-floor enforced by `tests/ui/test_a11y_floor.py` and
  `tests/ui/test_v21_sparklines_and_a11y.py`. Filter chips emit
  `aria-pressed` so screen readers announce the active filter.

## Numbers

- 6 files (2 new, 4 modified). ~290 lines of Python + Jinja + Alpine.
- 1961 → 1977 tests (+16, includes a11y reruns that now include
  jobs.html). mypy --strict clean on 66 source files. ruff src/ tests/
  clean.

## Design notes

### Two distinct shape contracts for the inbox vs the dashboard

The inbox tool (`recall_pending_results`) is per-inbox and FIFO on
`completed_at`. The dashboard list is process-wide and ordered by
`queued_at DESC` (newest first). Same `JobStore`, different read
methods (`list_pending_for_inbox` vs `list_recent`), different sort
orders. Pre-thinking this in v22.0.0a2 saved having to retrofit two
views over the same query later.

### Lazy-fetch full payload (carry-forward from v21.0.8)

`/api/delegated-jobs` returns full rows including `output` and `error`
because they're already capped at the backend `output_word_cap`
(default 800 words) — typically a few KB per row. The dashboard chat
tab's preview-vs-full split (v21.0.8) was about an unbounded
`question_full` column; here the output is already bounded so we ship
it inline. The single-row endpoint (`/api/delegated-jobs/{job_id}`)
exists for the same shape consistency as the MCP tool, not for
payload-size reasons.

### Status filter is client-side state, server-side query

The Alpine board reuses one fetch URL with a status query param,
re-fetching when the filter changes. Server-side filter rather than
client-side filter so the operator's "Failed" view stays under the
`limit=200` cap even when thousands of completed jobs sit in the
store.

## Carry-over to v22.0.0 GA

- Drop alpha designation in `__init__.py`.
- Comprehensive arc retro covering a1+a2+a3+a4.
- README badge / status bump.
- Architecture-doc section refresh covering the full delegate surface
  (sync/async, allow_writes, inbox, UI).
- Optional polish: stream-update the counter strip via SSE (the
  `/api/network/stream` pattern would fit). Deferred unless an
  operator hits it as a real friction point.

## Operator-facing note

After upgrading to v22.0.0a4, every harbormaster instance gains a
`/jobs` route at the same auth as the rest of the dashboard. The
JobStore writes to `~/.harbormaster/delegated_jobs.db` by default
(override via `$HARBORMASTER_JOBS_DB`); the file is created on
first call to any async-delegate or get-status tool, not at server
boot. If the dashboard daemon is upgraded before the stdio MCP
processes restart, the dashboard will see the JobStore as empty until
a stdio session fires an async-delegate call.

# Sprint Retro — Harbormaster v23.0.0a5

**Date:** 2026-05-13
**Theme:** Fourth and final routes-split alpha before GA. The 6
history-admin endpoints (reembed trigger, cancel, state, runs log,
2-way diff, N-way compare) move from `routes.py` into
`routes_history.py`.

## What landed

| File | Subject |
|---|---|
| `src/harbormaster/ui/routes_history.py` | new — 6 endpoints + `register_history_routes(app, config)` |
| `src/harbormaster/ui/routes.py` | inline block (~260 LOC) replaced by import + register call |
| `src/harbormaster/__init__.py` | 23.0.0a4 → 23.0.0a5 |
| `docs/sprint-retro-harbormaster-v23.0.0a5.md` | this file |

## Numbers

- 4 files (2 new, 2 modified). Net LOC ~0 (code moved).
- `routes.py`: ~2600 → ~2340 LOC (-260). Biggest single-alpha drop
  of the v23 split arc. Cumulative across a1, a3, a4, a5: 3064 →
  ~2340 (-724, **-24%**).
- 2013 → 2013 tests (unchanged). No source-grep retargeting needed
  (history routes have no heartbeat assertion).
- mypy --strict clean on 73 source files (was 72). ruff clean.

## Design notes

### No `render` arg for routes_history

History endpoints are all JSON / API only — no HTML page. The
`register_history_routes(app, config)` signature drops the
`render: RenderFn` parameter that v23.0.0a1, a3, a4 carried. Clean
typing: the function only needs what it uses.

This is a small future hint — when the dashboard / projects-detail
templates eventually split (likely v24+), each `register_*_routes`
will declare exactly the closures it needs. No god-object "context"
bundle.

### Python-script delete vs Edit string match

The history block was 260 LOC across 6 endpoints. Doing this as a
single Edit `old_string`/`new_string` would have been brittle (huge
multi-line block, easy to mismatch indentation). Used a
self-contained Python snippet via Bash to delete by line range,
verified by start/end markers (placeholder + the `/api/recall`
decorator).

Pattern worth keeping: for chunked routes-split extractions where
the boundary is unambiguous (decorator-to-decorator), Python
line-range delete is cleaner than Edit's substring match.

## Cumulative split arc (a1 + a3 + a4 + a5)

| Alpha | Extracted | routes.py before → after | LOC removed |
|---|---|---|---|
| v23.0.0a1 | routes_jobs.py (5 endpoints) | 3064 → 2914 | -150 |
| v23.0.0a3 | routes_network.py (6 endpoints) | 2914 → 2760 | -154 |
| v23.0.0a4 | routes_dispatcher.py (4 endpoints) | 2760 → 2600 | -160 |
| v23.0.0a5 | routes_history.py (6 endpoints) | 2600 → 2340 | -260 |
| **Total** | **21 endpoints → 4 focused modules** | **3064 → 2340** | **-724 (-24%)** |

What's still in routes.py after v23.0.0a5:
- `/` dashboard HTML (multi-tab, lots of state)
- `/projects/{name}` per-project page
- `/tools/fan-out` HTML
- `/api/health`, `/api/auth/cookie`
- `/api/hosts/budget`, `/api/tools/budget`, `/api/projects/budget`,
  `/api/projects/{name}/budget` (4 budget endpoints — could split
  next)
- `/api/settings/accent` GET + PUT
- `/api/bridge/status`, `/api/recall`, `/api/trajectories`,
  `/api/plugins`, `/api/config/diff`
- `/agent-card/{name}`, `/static/{path}`, `/mcp/{server}` proxy
- Sidebar Hide list endpoints
- KPI history + memory revisions
- `@app.on_event("startup")` warmup task
- `_render` closure + builder helpers + lifespan glue

That's still ~2340 LOC across ~30 endpoints + the shell. Splitting
budget endpoints is the obvious v24 candidate but they're stable
and don't crowd the sprint surface like the v22 / history blocks
did. v23 GA can call the split arc "done for now".

## Carry-over to v23.0.0 GA

Next ship is the final v23.0.0 GA:

1. Drop alpha designation in `__init__.py` (23.0.0a5 → 23.0.0).
2. Write comprehensive v23.0.0 retro covering a1-a5 + the v23 line.
3. Update README + `architecture-harbormaster.md` + `v22-final-summary`
   memory (rename to `v23-final-summary`).
4. Tag `v23.0.0` + PyPI publish.

After GA, v24 candidates from the v23 carry-overs (all noted earlier):
multi-worker JobWorker concurrency, FleetQ Bridge completion-push
channel, `notifications/resources/updated` when client surfacing is
ready, optional `auto_commit=True`, and the remaining template /
budget-route splits.

## Operator-facing note

After upgrading to v23.0.0a5:

- **No behaviour changes.** All 6 history endpoints (`POST /api/history/reembed`,
  `POST /api/history/reembed/cancel`, `GET /api/history/state`,
  `GET /api/history/reembed/runs`, `GET /api/history/reembed/runs/diff`,
  `GET /api/history/reembed/runs/compare`) behave identically.
- `[history]`-disabled operators continue to get 503 on mutations
  and canonical-empty shapes on reads — same shape as pre-v23.0.0a5.
- The dashboard's reembed control + run-history panel + N-way
  compare are unchanged.

# Sprint Retro — Harbormaster v23.0.0a3

**Date:** 2026-05-13
**Theme:** Second routes-split alpha. The 6 network endpoints
(HTML page + 5 API endpoints, previously split around
`/api/hosts/budget` in `routes.py`) move into `routes_network.py`.
Same `register_*_routes(app, config, render)` seam as v23.0.0a1.

## What landed

| File | Subject |
|---|---|
| `src/harbormaster/ui/routes_network.py` | new — 6 endpoints (1 HTML + 5 API: events, events/{id}/full, stats, sources, stream) + `register_network_routes()` |
| `src/harbormaster/ui/routes.py` | two inline blocks (~150 LOC) replaced by a single import + register call |
| `tests/ui/test_heartbeat_tuning.py` | updates the network-stream source-grep test to look at routes_network.py |
| `src/harbormaster/__init__.py` | 23.0.0a2 → 23.0.0a3 |
| `docs/sprint-retro-harbormaster-v23.0.0a3.md` | this file |

## Numbers

- 5 files (2 new, 3 modified). Net LOC ~0 — code moved, not added.
- `routes.py`: was ~2914 → now ~2760 LOC (-154). Second measurable
  reduction in two alphas.
- 2013 → 2013 tests (unchanged). One test (`test_heartbeat_tuning`)
  needed retargeting to the new file location.
- mypy --strict clean on 71 source files (was 70). ruff clean.

## Design notes

### Block consolidation as a side-benefit

The pre-v23.0.0a3 routes.py had network endpoints split across two
chunks: lines 186-289 (HTML + events + events/{id}/full + stats)
AND lines 834-886 (sources + stream). `/api/hosts/budget` had been
inserted between them historically. The extraction not only reduced
LOC but **consolidated the network surface** — all 6 endpoints live
in one file, in one register call.

This is a real maintainability win: a contributor adding a 7th
network endpoint now knows there's exactly one place to put it.

### Source-grep tests need maintenance on split

`tests/ui/test_heartbeat_tuning.py::test_network_stream_uses_config_heartbeat_value`
asserts at the source level (reads routes.py text, greps for the
config attribute). When a route moves to a new file, the source-grep
target moves with it. Captured as a one-line edit + comment
referencing v23.0.0a3.

**Lesson:** source-grep assertions are a maintenance debt for any
refactor that moves their target. Worth keeping for the "did we
forget to wire X?" coverage, but accept the cost. Next time the
routes split touches a source-grepped surface, the test edit is part
of the alpha.

## Carry-over

- v23.0.0a4: `routes_dispatcher.py` (3 endpoints).
- v23.0.0a5: `routes_history.py` (5 history-admin endpoints).
- v23.0.0 GA: drop alpha + comprehensive arc retro covering
  a1-a5.

After v23.0.0a5, `routes.py` should be down from 3064 LOC →
roughly 2400 LOC. Still big, but every remaining chunk is a focused
surface (dashboard, projects, plugins, A2A cards, MCP proxy, auth,
config) rather than the kitchen-sink it was at v22.2.0.

## Operator-facing note

After upgrading to v23.0.0a3:

- **No new endpoints, no removed endpoints, no signature changes.**
- The 6 network endpoints (`/network`, `/api/network/events`,
  `/api/network/events/{id}/full`, `/api/network/stats`,
  `/api/network/sources`, `/api/network/stream`) behave identically.
- The dashboard /network page and SSE auto-update continue to work
  unchanged.
- If `tests/ui/test_heartbeat_tuning.py::test_network_stream_uses_config_heartbeat_value`
  fails after a future refactor, check that
  `routes_network.py` still has the `config.server.heartbeat_interval_network_s`
  reference — that's what the assertion proves.

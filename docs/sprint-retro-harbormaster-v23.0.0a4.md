# Sprint Retro — Harbormaster v23.0.0a4

**Date:** 2026-05-13
**Theme:** Third routes-split alpha. The 4 dispatcher endpoints
(HTML waterfall + recent/trace/status APIs) move from `routes.py`
into `routes_dispatcher.py`.

## What landed

| File | Subject |
|---|---|
| `src/harbormaster/ui/routes_dispatcher.py` | new — 4 endpoints + `register_dispatcher_routes()` |
| `src/harbormaster/ui/routes.py` | inline block (~160 LOC) replaced by import + register call |
| `tests/ui/test_heartbeat_tuning.py` | retargets the dispatcher-trace source-grep to the new file |
| `src/harbormaster/__init__.py` | 23.0.0a3 → 23.0.0a4 |
| `docs/sprint-retro-harbormaster-v23.0.0a4.md` | this file |

## Numbers

- 5 files (2 new, 3 modified). Net LOC ~0 (code moved).
- `routes.py`: ~2760 → ~2600 LOC (-160). Third reduction in three
  alphas; total ~3064 → ~2600 (-464, -15%).
- 2013 → 2013 tests (unchanged). One source-grep retargeted.
- mypy --strict clean on 72 source files (was 71). ruff clean.

## Design notes

### The `[fleetq]` extra fallback travels with the extraction

`api_dispatcher_recent`, `api_dispatcher_trace`, and
`api_dispatcher_status` all wrap their `harbormaster.fleetq` import
in `try / except ImportError`, returning canonical-empty responses
when the extra isn't installed. That behaviour is unchanged — the
imports are still inside the handler bodies (matches the dispatcher
endpoints' pre-v23.0.0a4 shape). No new failure mode in operator
environments without `[fleetq]`.

### Source-grep test retargeting is now a pattern

Second consecutive alpha to update `test_heartbeat_tuning.py` —
v23.0.0a3 retargeted `_network_s`, v23.0.0a4 retargets `_trace_s`.
The pattern is consistent: alpha extracts route → source-grep test
points at the new file. Next alpha (v23.0.0a5 / history admin)
won't need this update because history doesn't have a heartbeat
assertion. v23.0.0 GA can declare the source-grep maintenance debt
"resolved" once the routes split is done.

## Carry-over

- v23.0.0a5: `routes_history.py` (5 history-admin endpoints).
  Likely the last extraction before GA — remaining routes (dashboard
  HTML, projects/{name}, plugins, A2A cards, MCP proxy, auth,
  config, accent, KPI, sidebar Hide list) are smaller surfaces that
  can stay in `routes.py` for v23.

## Operator-facing note

After upgrading to v23.0.0a4:

- **No behaviour changes.** All 4 dispatcher endpoints (`/dispatcher`
  page + `/api/dispatcher/{recent,trace,status}`) behave identically.
- `[fleetq]`-disabled operators continue to get canonical-empty
  responses with no `ImportError` surfacing to the user.
- The dispatcher trace waterfall page (`/dispatcher`) continues to
  consume `/api/dispatcher/trace` SSE for live spans + replays
  missed completed spans via `Last-Event-ID` on reconnect (v9.0.0a4
  behaviour preserved).

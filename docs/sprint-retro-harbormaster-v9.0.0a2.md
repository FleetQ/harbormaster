# Sprint Retro — Harbormaster v9.0.0a2

**Date:** 2026-05-10
**Phase:** v9.0 Phase 2 — `/api/dispatcher/status` real endpoint
**Branch:** `feat/v9.0-dispatcher-status`

## What shipped

The sidecar metrics endpoint the v7.0.0a5 dispatcher CLI docstring
already promised. The dashboard's KPI strip stops lying about
dispatcher state; the v9 trace waterfall (Phase 3) gets a clean
data source; operators get a CLI flag to peek at a remote
deployment.

| Artifact                                                | Purpose                                                                          |
|---------------------------------------------------------|----------------------------------------------------------------------------------|
| `harbormaster.fleetq.dispatcher.DispatcherStats`         | Thread-safe per-tool counters + in-flight spans + `last_dispatched_at`           |
| `MCPDispatcher.dispatch()` instrumentation              | Records start/end through the singleton on every dispatch                        |
| `GET /api/dispatcher/status`                            | Canonical v9.0.0a2 schema; empty-shape fallback when [fleetq] absent             |
| `dispatcher_cli --url <base-url>`                       | Fetches the endpoint, merges runtime block into `--json` output / text print     |
| `/api/kpi` `dispatcher` field derivation                 | `>0 active` / `idle` / `ready` (string-stable; same template binding)            |
| `tests/ui/test_dispatcher_status_endpoint.py`           | 8 endpoint tests (empty shape, schema, counters, in-flight observation, KPI)     |
| `tests/unit/test_dispatcher_cli_url.py`                 | 3 CLI tests (merge, fallback, text format)                                       |

## Numbers

* **Tests:** 960 → 971 (+11; +1.1%)
* **Source files:** 52 → 52 (no new modules; metrics live alongside the dispatcher)
* **mypy --strict + ruff:** clean
* **Backwards-incompatible:** 0 user-facing
* **New `dispatch` overhead:** 2 lock acquires per call. The per-tool counter dict + 1-element list mutation; ~1µs on a hot path that already does sub-ms work. No new threads, no I/O.

## Schema (canonical)

```json
{
  "running": [
    {"tool": "ask_project", "project": "demo", "started_at": 1700000000.0}
  ],
  "active_workers": 1,
  "queue_depth": 0,
  "last_dispatched_at": 1700000000.5,
  "tools": {
    "ask_project": {"in_flight": 1, "total_completed": 5, "total_failed": 0}
  }
}
```

`queue_depth` is always `0` for the in-process dispatcher. The field
is preserved so consumers do not have to special-case the in-process
vs. pool-backed deployment when v10 introduces a real bounded pool.

## Deviations from the phase plan

### 1 · `dispatcher.status()` not added as an instance method

**Plan said:** "extend `harbormaster.dispatcher` ... to expose state via
a new `Dispatcher.status()` method".

**What shipped:** module-level singleton + `get_dispatcher_stats()`
function. Reasoning: the in-process `MCPDispatcher` is constructed
per request flow inside `__main__.py` + the relay; if `status()` were
an instance method, the UI route would need a reference to *that
specific instance*, but the UI process and the relay process can be
different deployments. A process-wide singleton dodges the
plumbing problem and gives the same observability for both
deployments. Documented in the dispatcher module so v10 can revisit
if a per-instance metrics view becomes useful.

### 2 · `tests/ui/test_kpi_endpoint.py::test_kpi_dispatcher_placeholder_ready` updated

**Plan said:** "Update KPI strip ... to use real dispatcher data".
The KPI test expected `"ready"` because v8.0.0a5 hardcoded it. The
v9.0.0a2 derivation produces `"ready"` only on a cold dispatcher;
once any other test in the suite has run a dispatch through the
singleton, the field flips to `"idle"`. The test now resets the
singleton at the top.

This is a **test isolation** edit, not a contract change — the
returned shape (string under `dispatcher`) is unchanged.

## What worked

* **Singleton + `record_start`/`record_end` pattern.** The simplest
  thread-safe metrics implementation that doesn't require a real
  pool. One `threading.Lock`, no atomics, no fancy compare-and-swap.
  Total lines: ~110 including docstrings.
* **`isError`-envelope detection for failure counting.** The
  dispatcher already wraps every error path in
  `_error_envelope(...)`. Re-using that signal as the failure source
  means we don't have to change `_handle_call`'s error logic — we
  just observe the resulting envelope.
* **Soft-disable when [fleetq] is absent.** The endpoint always
  responds with the canonical empty shape, so dashboards don't 500.
  Same pattern `/api/kpi` uses.
* **`--url` flag uses stdlib `urllib.request`.** No new dep; the CLI
  already had `httpx` available transitively but reaching for it
  would force a soft-import dance. Stdlib is fine for a 1-shot GET.

## What we'd do differently

* **Document the singleton's process scope explicitly in docs/.**
  Operators running a remote harbormaster-ui + a separate
  harbormaster-mcp (FleetQ relay) deployment will see *two*
  dispatchers, each with its own counter set. The CLI's `--url`
  hits one process; the relay's metrics aren't visible from the
  UI yet. v10 candidate: a metrics-aggregator endpoint that
  multiplexes across declared peers.
* **Consider a `since=<timestamp>` query parameter.** The current
  endpoint is a pure snapshot; for time-series consumers (Grafana
  scrapes) we'd want windowed counters. Not needed yet — the KPI
  strip + waterfall are point-in-time consumers.

## Forward to v9.0.0a3

Phase 3: Trace waterfall surface. New `/dispatcher` page rendering
live trace spans via SSE. Will consume the same singleton — the
`record_start` / `record_end` pair already produces the events the
waterfall needs (the ring-buffer for last-N completed traces is the
new piece).

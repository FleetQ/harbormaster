# Sprint Retro — Harbormaster v5.0.0a1

**Date:** 2026-05-09
**Theme:** Closed both v4.0.0a5 deferrals — auto-reembed got a UI
panel and exponential-backoff retry. The endpoint added in v4 finally
has a consumer.

## What landed

| SHA | Subject |
|-----|---------|
| `310813e` | feat(history+ui): auto-reembed UI panel + retry |

## Capabilities (this sprint)

### 1 · Dashboard auto-reembed panel

`reembedPanel()` Alpine component on the dashboard:

- Polls `/api/history/state` on mount; auto-polls every 3s while
  phase=`running`; stops on terminal phase
- Phase badge with semantic colours (cyan / emerald / rose / gray)
- Progress bar bound to `processed / total`
- Shows current host being processed
- Surfaces `last_error` on failed
- Hidden when no run has happened AND auto-reembed isn't enabled
  in config — dashboard stays uncluttered for operators who never
  opted in

### 2 · Exponential-backoff retry

`_reembed_one_host` now retries on transient open/reembed failures:

```python
_RETRY_BACKOFF_SECONDS = (1.0, 2.0, 4.0)
# 1 initial + 3 retries = 4 attempts max per host (7s total wait)
```

Both paths (QAStore.open + store.reembed) get the retry loop. Permanent
failures (e.g. corrupt DB) surface as `"... after 4 attempts: ..."`
in the runner's `error` field.

### 3 · Test suite stays fast

`pytest.fixture(autouse=True)` zeroes `_RETRY_BACKOFF_SECONDS` for
unit tests. The retry behaviour itself is verified by counting
attempts, not wall-clock — so the failure-isolation test stays fast
even though it exercises the retry path multiple times.

## Real numbers

- 1/1 v4 retro action item shipped (the bundled UI panel + retry)
- 0 PRs opened — merged via `git merge --no-ff`
- 7 new unit tests (3 retry + 4 UI panel)
- Test suite delta: 670 + 2 skips → **677 + 2 skips**
- `mypy --strict` clean across 49 source files
- `ruff` clean across `src/` and `tests/`
- 0 backwards-incompatible changes — the panel is purely additive,
  the retry is transparent to callers

## What worked

- **Same retry pattern in two places.** Open and reembed each get
  the same `for attempt, delay in enumerate((0.0, *_BACKOFF), start=1)`
  loop. Identical structure, easy to read, easy to extend if a third
  call site needs the same treatment.
- **Autouse fixture for backoff override.** Adding the retry without
  an override would have made the failure-isolation test go from
  ~50ms to ~14s (2 hosts × 7s each). The autouse fixture keeps the
  suite snappy without coupling test_auto_reembed to retry internals.
- **Panel auto-hides when not relevant.** The empty-state check
  `phase === 'idle' && !auto_reembed_enabled` keeps the dashboard
  uncluttered for the >50% of operators who'll never enable auto-reembed.
- **3s poll cadence.** Fast enough to track a 30-second reembed
  visually; slow enough to not flood the UI process. Matches the
  bridge state's stale-after-30s threshold conceptually.

## What to change / next

- **Polling stops on phase=done; never restarts.** A second auto-reembed
  run (e.g. after another model bump + restart) won't surface in
  the UI without a manual page reload. Acceptable — auto-reembed
  is a startup-only flow today; a future "trigger reembed manually"
  button could re-arm polling.
- **No "running for X seconds" ETA.** Could compute from
  `started_at` and the rate of `processed` increments, but it'd be
  noisy unless there's a clear total estimation. Defer.

## Action items for the next sprint (v5.0.0a2)

1. **Stress test for backend-invoking tools.** Wire
   `tests/fixtures/fake_claude.py` into
   `tests/integration/test_dispatcher_stress.py`. Cover ask_project
   and delegate_task under 50-concurrent dispatch. If green, the
   v4.0.0a6 dispatcher pool is safe across the whole tool surface;
   if a thread-safety issue surfaces, ship the test as a regression
   guard and defer the all-tools opt-in.

## Out-of-scope (still)

- Tauri / Electron desktop UI — no demand.
- Relay-binary path (Path B) — Path C HTTP tunnel covers it.
- IDE extension — MCP works with any MCP client.
- Session-cookie auth + CSRF — defer until multi-operator UI is real.
- pnpm v5 lockfile support — pre-2022 format.
- Manual "trigger reembed now" button — defer until needed.
- Reembed ETA estimation — defer until rate signal stabilises.

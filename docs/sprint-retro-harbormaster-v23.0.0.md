# Sprint Retro — Harbormaster v23.0.0 (GA)

**Date:** 2026-05-13
**Theme:** The routes split + operator-realistic defaults sprint.
Closes the long-deferred structural debt flagged across the v21
and v22 retros. Five alphas in one day: a1 (jobs) + a2 (timeouts /
retention) + a3 (network) + a4 (dispatcher) + a5 (history). GA
drops the alpha and writes the comprehensive arc retro.

## Tags published

| Tag | Type | Capability |
|-----|------|------------|
| v23.0.0a1 | refactor | Extract `routes_jobs.py` (5 endpoints) |
| v23.0.0a2 | feat | timeout_local 60→300, timeout_remote 120→600, total_timeout 120→600, new `[delegate] retain_recent_k=1000` + JobStore pruning |
| v23.0.0a3 | refactor | Extract `routes_network.py` (6 endpoints) |
| v23.0.0a4 | refactor | Extract `routes_dispatcher.py` (4 endpoints) |
| v23.0.0a5 | refactor | Extract `routes_history.py` (6 endpoints) |
| **v23.0.0** | GA | Drop alpha; arc retro; memory + doc refresh |

6 published versions in the v23 line. Latest on PyPI: **v23.0.0**.

## Numbers (cumulative across v23)

- 6 ships on feature branches, all fast-forward merged to main
- 2008 → 2013 unit + integration tests (+5)
- mypy --strict + ruff clean (69 → 73 source files, +4 new
  routes_* modules)
- 0 backwards-incompatible MCP / HTTP surface changes
- `routes.py` shrunk: **3064 → ~2340 LOC (-724, -24%)** across 4
  extraction alphas
- ~600 LOC added across the new routes_* modules (close to LOC-net
  zero on the extractions; v23.0.0a2 added ~150 net LOC for
  retention + tests)

## Routes split — what landed (a1, a3, a4, a5)

| Alpha | Module | Endpoints | LOC removed from routes.py |
|---|---|---:|---:|
| v23.0.0a1 | `routes_jobs.py` | 5 | -150 |
| v23.0.0a3 | `routes_network.py` | 6 | -154 |
| v23.0.0a4 | `routes_dispatcher.py` | 4 | -160 |
| v23.0.0a5 | `routes_history.py` | 6 | -260 |
| **Total** | **4 modules** | **21** | **-724** |

Each extraction uses the same `register_*_routes(app, config, render?)`
callable-seam pattern. Future contributors adding a 7th endpoint to
any of these surfaces know exactly where to put it.

## Operator-realistic defaults (a2)

| Config | v22.2.0 | v23.0.0 |
|---|---:|---:|
| `BackendConfig.timeout_local` | 60s | **300s** |
| `BackendConfig.timeout_remote` | 120s | **600s** |
| `HostConfig.total_timeout` | 120s | **600s** |
| `[delegate] retain_recent_k` | — | **1000** (new) |

Operators with explicit TOML values are unaffected. Bare-default
users picking up v23 see realistic budgets for v22's async writes
shape. Source: `docs/budget-audit-2026-05-13.md`.

## Patterns established (carry forward to v24+)

### `register_*_routes(app, config, render)` callable seam

Each split module exports a `register_*_routes` function. Caller
(`routes.py`'s `create_app`) passes:
- `app: FastAPI` — the application instance
- `config: HarbormasterConfig` — the loaded config (closes over
  config-shaped state needed by the routes)
- `render: RenderFn` (optional) — the `_render(request, template,
  extra) -> HTMLResponse` closure that captures templates +
  auth_ctx + base_ctx + version

This shape lets each module declare exactly the closures it needs.
`routes_history.py` (no HTML) drops the `render` arg. Future split
modules will follow the same minimalism — no god-object "context"
bundle.

### Preserved FastAPI route ordering

FastAPI matches routes by registration order. Each `register_*_routes`
call is placed where the inline block lived, so resolution order is
unchanged. The one exception is `routes_network.py`: the pre-split
network surface was split around `/api/hosts/budget` (one chunk
above, one below). The extraction consolidates all 6 endpoints into
one register call at the upper block's location. Path namespaces
don't collide, so the consolidation is safe.

### Source-grep tests retarget on extraction

`tests/ui/test_heartbeat_tuning.py` has two source-grep assertions
that point at the file containing
`config.server.heartbeat_interval_*_s`. When routes moved, the
greps moved. One-line edits in v23.0.0a3 (network) and v23.0.0a4
(dispatcher). After v23.0.0 GA, the only remaining
source-grep is for streaming heartbeat (still in routes.py).

### Python line-range delete vs Edit string match

For unambiguous decorator-to-decorator boundaries (260-line history
block in v23.0.0a5), a self-contained Python script via Bash that
deletes by line range is more robust than Edit's exact-substring
match. Pattern: read file, find start/end markers, slice, write back.

### Idempotent ADD COLUMN + retention pruning pattern

v23.0.0a2's `JobStore.prune_old(retain)` is a one-shot at subsystem
init, AFTER `recover_orphaned()` so any leftover `running` rows from
a prior process get to a terminal state first. Retention is
**delete-by-rank**: keep the most-recent N by `queued_at`. Defensive
no-op when `retain < 1`. Pattern mirrors `history.retain_recent_k`
semantics.

## v23 design rationale

### Why ship retro debt as a sprint

The v21 retro (4cd6815) and v22 retros all flagged the same
structural debt: `routes.py` at 3000+ LOC, `dashboard.html` 3064,
`project_detail.html` 1964 — "split deferred to v22 / v23
architecture sprint" — which kept getting pushed because feature
work crowded it out. The 2026-05-13 cool-down day finally made the
call: **the next sprint line starts with the deferred split, not
features.**

This works because:
- Each extraction is a tiny risk surface (file move, no behaviour
  change)
- Each gets its own version + retro (clear bisect surface for
  later regression)
- Tests pass at every step (2013 → 2013 across all 4 splits)
- The pattern compounds — adding a 5th endpoint to any module is
  now obvious

### Why mix a2 (defaults) in the middle

v23.0.0a2 (timeout defaults + retention) interrupts the otherwise-
pure routes-split arc (a1 → a3 → a4 → a5). The reason: the budget
audit doc from cool-down day surfaced four operator-realistic
defaults that should land BEFORE any operator gets the v23 line
upgrade. Bundling them as a2 ships them with the very first
non-refactor change of v23, meaning every v23 line picks them up.
Routes-split resumed at a3.

### Why GA at 5 alphas, not more

After v23.0.0a5, `routes.py` is ~2340 LOC. Still big, but every
remaining chunk is a focused surface (dashboard HTML, projects
detail, plugins, A2A cards, MCP proxy, budgets, KPI, sidebar Hide
list) and **none are crowding the sprint surface like the v22 +
history blocks did**. The budget-routes split is a small, optional
v24 candidate but doesn't have the same "deferred for two sprints"
debt signal. GA now; resume splits when they become a friction
point again.

## Lessons

### "Deferred" is a debt label that compounds silently

`routes.py` carried a "split deferred to v22" label from v21.0.9.
v22 chose async-delegate features instead. By the time the v22
retro flagged the same file as the only soft-signal on an otherwise
8.6/10 health card, it had grown another ~500 LOC. The longer
"deferred" sits without a date, the more code piles onto the
deferred chunk. **Rule**: every retro that says "deferred to vN+1"
must declare the alpha number that will execute it (e.g. "v23.0.0a1
= routes split").

### Refactor alphas don't need new tests, but they DO need a retest

a1, a3, a4, a5 added zero new tests — the existing 2008+ tests
exercise the same surface via the same URLs. But each alpha
required a FULL test run + mypy + ruff after the move, and a3 / a4
needed source-grep test retargeting. The check pipeline is the same
shape as a feature alpha; only the deliverable shape differs.

### `retain_recent_k = 1000` is a placeholder pending real usage

The v23.0.0a2 retention default was picked by mirroring
`history.retain_recent_k`. It hasn't been calibrated against actual
delegated_jobs.db growth in operator practice (we have 3 rows in
production right now). When the volume gets meaningful, revisit
whether 1000 is the right cap — could be too tight for heavy
delegators, or too loose for storage-constrained operators. Capture
in v24 backlog.

## Cumulative session totals (2026-05-06 → 2026-05-13)

Updated from the 2026-05-13 weekly retro:

- **48 published PyPI versions** (was 24 at start of day; v23 added
  6 ships)
- 489 + 6 = **495 commits over 6 days** (still single contributor)
- 2008 → 2013 tests (+5 net for v23, mostly retention tests)
- mypy --strict + ruff clean throughout
- 0 force-pushes to main, 0 PyPI yanks within a GA line

## v24+ candidates (out of v23 scope)

1. **Multi-worker JobWorker concurrency** — atomic claim already
   supports it; needs `[delegate] worker_count = N` config knob.
2. **FleetQ Bridge completion-push channel** — Pusher event per
   `_fire_completion` so cross-machine agents can react.
3. **`notifications/resources/updated`** when MCP clients gain
   reliable subscription forwarding.
4. **Budget-routes split** (`/api/{hosts,tools,projects}/budget`) —
   small, optional. Wait for friction.
5. **Template splits** — `dashboard.html` (3064 LOC),
   `project_detail.html` (1964 LOC). Same "deferred" pattern that
   v23 just resolved for `routes.py`.
6. **Recalibrate `retain_recent_k=1000`** based on real operator
   usage data.
7. **Optional `auto_commit=True`** for write-mode async jobs.
8. **Per-call max_turns recommendations surfaced in the UI** —
   empirical guideline from v22.0.1 lives in retros + memory but
   the dashboard could nudge.

## Operator-facing upgrade note (v22.x → v23.0.0)

After `uv tool upgrade harbormaster-mcp` to v23.0.0:

### What's new

- **Default timeouts bumped** to v22-realistic values (300s local,
  600s remote / SSH). Affects operators on bare defaults.
- **New `[delegate] retain_recent_k = 1000`** config block. Default
  prunes oldest `delegated_jobs` rows beyond 1000.
- **No new endpoints, no removed endpoints, no signature changes.**
  All 21 extracted endpoints behave identically — they just live in
  4 new files.

### What's structurally changed (relevant if you read source)

- `src/harbormaster/ui/routes.py` shrunk from 3064 → ~2340 LOC.
- New files: `routes_jobs.py`, `routes_network.py`,
  `routes_dispatcher.py`, `routes_history.py`. Each exports
  `register_*_routes(...)`.
- `routes.py` calls each `register_*_routes` at the original block's
  position, preserving FastAPI route resolution order.

### Standard verification after upgrade

```bash
launchctl kickstart -k gui/$(id -u)/com.harbormaster.ui
launchctl kickstart -k gui/$(id -u)/com.harbormaster.mcp
curl -s http://127.0.0.1:7531/api/health   # expect "version":"23.0.0"
curl -s http://127.0.0.1:7531/api/delegated-jobs/summary  # triggers JobStore init + pruning
```

`incident-playbook` Serena memory entries #1-#6 still apply. The
v22 max_turns_reached debugging recipe is unchanged. The async
delegate flow (sync / async / inbox / await tools) is unchanged.

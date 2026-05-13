# Sprint Retro — Harbormaster v23.0.0a2

**Date:** 2026-05-13
**Theme:** Operator-realistic defaults + storage hygiene. Three
backend timeouts bumped to fit v22 writes-mode workloads; new
`delegated_jobs` retention prevents unbounded growth. All four items
from `docs/budget-audit-2026-05-13.md` shipped together.

## What landed

| File | Subject |
|---|---|
| `src/harbormaster/config.py` | `BackendConfig.timeout_local: 60→300`, `timeout_remote: 120→600`, `HostConfig.total_timeout: 120→600`; new `DelegateConfig` block (retain_recent_k=1000) wired into `HarbormasterConfig` |
| `src/harbormaster/jobs/store.py` | new `JobStore.prune_old(retain)` — DELETE WHERE NOT IN (newest N by queued_at) |
| `src/harbormaster/jobs/subsystem.py` | wires `store.prune_old(retain=config.delegate.retain_recent_k)` into boot, AFTER `recover_orphaned()` |
| `tests/unit/test_jobs_prune.py` | new — 5 tests covering retain semantics, no-op edges, queued-job protection, subsystem-boot wiring |
| `tests/unit/test_config.py` | updates default assertions for the bumped timeouts + delegate block |
| `src/harbormaster/__init__.py` | 23.0.0a1 → 23.0.0a2 |
| `docs/sprint-retro-harbormaster-v23.0.0a2.md` | this file |

## Numbers

- 7 files (2 new, 5 modified). ~150 LOC.
- 2008 → 2013 unit + integration tests (+5). mypy --strict clean on
  70 source files. ruff src/ tests/ clean.

## Capabilities

### Defaults bumped (semantic change!)

| Config | v23.0.0a1 | v23.0.0a2 | Why |
|---|---:|---:|---|
| `BackendConfig.timeout_local` | 60s | **300s** | v22 writes with `max_turns=80` take ~800s; 60s was tight |
| `BackendConfig.timeout_remote` | 120s | **600s** | Same logic for SSH |
| `HostConfig.total_timeout` | 120s | **600s** | SSH stream lifetimes |

**Operators with explicit TOML values are unaffected** — Pydantic
override wins. Operators on bare defaults see longer timeouts on
first new write delegation.

### New config block

```toml
[delegate]
retain_recent_k = 1000  # keep most-recent N rows; older pruned on boot
```

### JobStore retention

`prune_old(retain)` runs ONCE per process at subsystem init, AFTER
`recover_orphaned()`. Mirrors `history.retain_recent_k` semantics —
newest wins, ordered by `queued_at` DESC. Currently in-flight rows
are protected because their `queued_at` is fresh.

## Design notes

### Why bump at GA-equivalent boundary, not later

The retro for v23.0.0a1 deferred this to "v23.0.0a2 or later", but
shipping it FIRST after the routes split has a payoff: every
operator who upgrades from v22 to v23 picks up the realistic
defaults in one step instead of needing two upgrades. The bumped
defaults are also a CORRECTNESS fix for the v22 writes path —
running on v22.x with default 60s timeout could silently kill long
delegations before they completed. v23.0.0a2 is the right step to
ship them.

### `recover_orphaned` first, then `prune_old`

Order matters: if pruning ran first, it could delete a row that was
`running` from a previous (now-dead) process before
`recover_orphaned` had a chance to mark it `failed`. By running
recovery first, every leftover row gets to a terminal state
(`failed:server_restart`), THEN pruning operates on a stable set.

### `retain < 1` is a no-op (defensive)

`prune_old(retain=0)` returns 0 deletions, not "delete all".
Operators with a corrupted config or a hand-edited
`retain_recent_k = 0` (if they thought "zero means disable") get a
no-op, not data loss. Captured as
`test_prune_old_with_retain_lt_1_is_noop`.

## Lessons

### Default-bump retro is a separate ship from feature work

It would have been tempting to fold this into v22.0.1 ("we caught
max_turns, while we're here let's bump timeouts too"). Resist that.
A default change has its own blast radius — operators reading their
own config files notice the diff. Shipping it ALONE means the
changelog is clear: "v23.0.0a2 = defaults + retention". No surprises
hidden in a feature bundle.

### Audit doc → backlog → ship is a clean loop

`docs/budget-audit-2026-05-13.md` was written as a research artefact
during the cool-down day; the "Items needing v23 action (4
candidates)" section listed exactly what shipped here. Pattern:
when retro flags structural debt, write a focused audit doc
FIRST, then ship from the doc rather than from memory. The audit
doc becomes the merge-criteria.

## Carry-over

v23.0.0a3+ resumes the routes split per v23.0.0a1's carry-over
section. Next extraction candidates (in order):

1. `routes_network.py` (4 endpoints, ~200 LOC) — v23.0.0a3
2. `routes_dispatcher.py` (3 endpoints, ~200 LOC) — v23.0.0a4
3. `routes_history.py` (5 endpoints, ~250 LOC) — v23.0.0a5
4. GA: comprehensive arc retro, drop alpha

## Operator-facing note

After upgrading to v23.0.0a2:

- **If you had no `[backends.claude]` block in your TOML**, your
  effective `timeout_local` was 60s; now it's 300s. SSH
  `total_timeout` was 120s; now 600s. **This is a behaviour change
  on bare defaults** — flag it if you have ops scripts that assume
  failure within 60s.
- **If you had explicit values**, nothing changes. Your TOML still
  wins.
- New TOML block, default `[delegate] retain_recent_k = 1000`. Bump
  if you delegate ≥1000 jobs/day and want longer history; lower if
  storage is tight.
- After upgrade + daemon kickstart, `delegated_jobs.db` gets pruned
  once at first subsystem init. Old rows beyond the cap disappear.
  Safe — they were complete / failed terminal rows; no in-flight
  work touched.

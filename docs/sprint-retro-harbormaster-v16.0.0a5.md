# Sprint Retro — Harbormaster v16.0.0a5

**Date:** 2026-05-10
**Theme:** Per-project budget — closes the budget triad alongside
v14.0.0a4 (per-host) and v15.0.0a4 (per-tool).

## What shipped

- **`HostProjectBudget` model + nested config** (carry-over #9).
  New Pydantic class wired into `HostConfig.projects: dict[str,
  HostProjectBudget]`. Operators write::

      [hosts.alpha.projects.frontend]
      daily_call_budget = 50

      [hosts.alpha.projects.backend]
      daily_call_budget = 100

  Tightest cap wins (per-host OR per-tool OR per-project) when more
  than one applies — pure min() over the three axes.
- **`GET /api/projects/budget?host=<name>` endpoint**. Mirrors
  `/api/tools/budget` shape::

      {"host": "alpha", "window_hours": 24,
       "projects": [
         {"project": "frontend", "calls_24h": 12, "budget": 50,
          "usage_pct": 24.0,
          "tightest_cap": 50, "tightest_cap_axis": "project"},
         ...]}

  `tightest_cap_axis` records which budget actually wins — the
  KPI strip cell hover tooltip can render a per-axis breakdown
  without re-doing the comparison client-side.
- **`NetworkStore.count_by_target_filtered()`**. Pushes the
  per-project filter down to SQLite (`WHERE target IN (...)`)
  instead of post-filtering in Python. Empty `targets` short-
  circuits to `{}` (no rows scanned). Targets not seen in the
  window still appear with count 0 so the caller renders
  "configured but never called" cells uniformly.
- **`examples/harbormaster.toml`** + **`docs/operator-config-
  reference.md`** updated with the new nested `[hosts.<host>.
  projects.<project_name>]` section. Doc-parity hook stays green.

## Numbers

- **Tests**: 1568 → 1580 (+12 net new — 3 model + 7 endpoint + 2
  helper)
- **Source files**: 57 (unchanged — extensions only; new model
  lives inside `config.py`, new endpoint in `routes.py`, new
  store helper in `network_store.py`)
- **Wall-clock**: ~25 min
- **Commits on main**: 1 feature merge
- **Lint / type**: ruff clean, `mypy --strict` clean
- **Backwards-incompatible changes**: 0
  - `HostConfig.projects` defaults to `{}` so every existing
    `[hosts.<name>]` parses byte-identically.
  - The new endpoint is additive; existing budget endpoints
    unchanged.
- **Confirmation: did NOT touch `.github/workflows/*`** — yes.

## What worked

- **Mirror, don't invent.** The endpoint shape mirrors
  `/api/tools/budget` (v15.a4); the helper shape mirrors
  `count_by_target` (v14.a4). Tests, docs, and example wiring
  followed by analogy.
- **`tightest_cap_axis` is a tiny addition with big payoff.**
  Without it, the KPI strip tooltip would have to re-do the
  three-way min in Alpine. With it, the operator sees "tool" /
  "host" / "project" labels straight from the API response.
- **Doc-parity catches new fields immediately.** The new
  `HostConfig.projects` field hit the v15.a5 parity gate on the
  first pre-test run — added one row to the doc reference and
  the gate went green. v16.a2's suggested-edit emitter would
  also have produced the row template (didn't need it this
  time, but the safety net was there).
- **CWD discipline held.** All Bash calls in this phase ran
  from the worktree CWD without explicit `cd`. Discipline
  lapses for v16.a5: **0**.

## What to change for the next phase

- v16.a6 is the highest-risk phase: trace waterfall true
  parent/child viz. Backend instrumentation + SSE event format
  changes carry the most risk; the waterfall renderer is the
  visible payoff. The split-to-a6.5 authorisation kicks in if
  the backend instrumentation alone takes >2hr.

## Notes for v16.a6 split decision

About to start. Will assess after the backend instrumentation
slice lands.

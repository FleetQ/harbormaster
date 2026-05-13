# Sprint Retro — Harbormaster v23.0.0a1

**Date:** 2026-05-13
**Theme:** Open the v23 line with the lowest-risk piece of the
long-deferred routes split. Extract the 5 v22 delegated-jobs
endpoints from `routes.py` (which has crossed 3064 LOC and accepts
70 changes/week) into a focused `routes_jobs.py` module. Zero
behaviour change. Future v23.0.0aN alphas continue with network,
dispatcher, history, and template splits.

## Triggering observation

`retro/retro-2026-05-13.md` (action item #1, only "soft" indicator
on the otherwise 8.6/10 health card): `routes.py` 70 changes in 7
days + `dashboard.html` 49 + `project_detail.html` 33 — all carry
"split deferred" labels from v21+v22 retros that **never executed**
because feature work crowded them out. Cool-down day chose the
smallest meaningful extraction as v23.0.0a1.

## What landed

| File | Subject |
|---|---|
| `src/harbormaster/ui/routes_jobs.py` | new — 5 endpoints (`/jobs` + 4 `/api/delegated-jobs*`) + `register_jobs_routes(app, config, render)` |
| `src/harbormaster/ui/routes.py` | inline block of ~150 LOC replaced by a 2-line `from ... import; register_jobs_routes(app, config, _render)` call |
| `src/harbormaster/__init__.py` | 22.2.0 → 23.0.0a1 |
| `docs/sprint-retro-harbormaster-v23.0.0a1.md` | this file |

## Capabilities

**None added.** v23.0.0a1 is a pure structural refactor — every
endpoint preserves its URL, signature, response shape, and
registration order. The `register_jobs_routes(app, config, render)`
seam is the only new surface; it accepts the same `_render` closure
`create_app` was already building, so context (templates, auth,
version) flows through unchanged.

## Numbers

- 4 files (2 new, 2 modified). Net LOC ~0 — code moved, not added.
- `routes.py`: was 3064 → now ~2914 LOC (-150). First measurable
  reduction since v21.
- 2008 → 2008 unit + integration tests (unchanged). All existing
  v22 tests pass against the new module without modification —
  confirms behaviour equivalence.
- mypy --strict clean on 70 source files (was 69 — `routes_jobs.py`
  is the new one). ruff src/ tests/ clean.

## Design notes

### The `RenderFn` callable seam

`_render(request, template, extra) -> HTMLResponse` is the closure
`create_app` builds — it captures `templates: Jinja2Templates` +
`auth_ctx: dict` + `base_ctx: dict` + `version: str`. The natural
move when extracting `jobs_page` would be to recreate this closure
in the new module, but that would duplicate context-building logic.

Solution: pass `_render` as a **callable parameter** to
`register_jobs_routes`. The module gets a `RenderFn` type alias for
clarity; the consumer (`routes.py`) passes its own `_render` directly.
No duplication; no leakage of `create_app`'s internals.

This is the pattern every future extraction (network, dispatcher,
history admin) will reuse — pass the closure(s) the routes need, do
not reimplement them.

### Preserved FastAPI route ordering

FastAPI matches routes by registration order. `/jobs` is static,
`/projects/{name}` is path-param — collision unlikely but possible
under future expansion. Kept registration order identical to the
pre-v23.0.0a1 inline block by calling `register_jobs_routes` at the
same call-site (between the network stream block and the
`/projects/{name}` route).

### Comment trail at the call site

```python
# v23.0.0a1: Delegated Jobs UI surface extracted to
# ``harbormaster.ui.routes_jobs`` — 5 endpoints, same registration
# order as the pre-v23.0.0a1 inline block. See module docstring
# there for the full rationale.
from harbormaster.ui.routes_jobs import register_jobs_routes
register_jobs_routes(app, config, _render)
```

Future contributors don't have to guess WHY the surface is split or
where to look for the endpoint code. The pattern is also the
documentation for the next extraction.

### Stdlib imports moved to module top

The pre-v23.0.0a1 inline block had `import asyncio`, `import time`,
`import json as _json` scattered inside each handler function. In
the extracted module, they're at module top — ruff prefers it,
mypy doesn't care, and "where do imports live" is one less question
for the reader.

## Lessons

### The smallest meaningful extraction is one cohesive feature, not one file

routes.py has many sub-surfaces: network, dispatcher, history admin,
plugins, A2A cards, MCP proxy. Picking "jobs" first was right because:

- It's the **newest** code (added this week in v22.0.0a4 + v22.2.0)
- It's the **most self-contained** (5 endpoints, one underlying
  subsystem)
- It has **dedicated tests** (`test_jobs_ui.py` + `test_jobs_sse_stream.py`)
  that exercise the surface without depending on routes.py internals
- Behaviour equivalence is **trivially verifiable** — same tests
  still pass

This is the criterion for the next alphas:
**newest + self-contained + has its own tests + can extract without behaviour change**.

### Pure refactors deserve their own version

It would have been tempting to bundle this with a feature ("v23.0.0:
routes split + multi-worker JobWorker"). Resist that. A pure refactor
shipped alone is:

- Trivially reverted if something breaks (one commit; no feature
  rollback needed)
- Easy to bisect — if a regression appears later, "did this start
  after v23.0.0a1?" has an unambiguous answer
- A clear signal in the changelog that the project is paying down
  debt, not just stacking features

### `routes.py` is still big — this is one step

After v23.0.0a1, `routes.py` is ~2914 LOC. Still hot. Subsequent
extraction candidates (sized by self-containment):

| Candidate | Endpoints | Approx LOC | Self-contained? |
|---|---:|---:|---|
| network | 4 (events, stream, events/{id}/full, stats) | ~200 | yes (has `network_log` module) |
| dispatcher | 3 (recent, trace, status) | ~200 | yes (FleetQ dispatcher module) |
| history admin | 5 (state, reembed/runs, reembed/runs/diff, reembed/runs/compare) | ~250 | yes |
| budgets | 3 (hosts/budget, tools/budget, projects/budget) | ~150 | mostly |

Pick highest-priority one for v23.0.0a2. The audit doc
(`docs/budget-audit-2026-05-13.md`) recommends v23.0.0a2 = timeout
bumps + JobStore retention instead, so routes splits resume at
v23.0.0a3+.

## Carry-over

### v23.0.0a2 candidates (one will become the next ship)

1. **`BackendConfig.timeout_local: 60 → 300`** +
   **`timeout_remote: 120 → 600`** +
   **`HostConfig.total_timeout: 120 → 600`** — captured in
   `docs/budget-audit-2026-05-13.md`. Single-commit, low risk,
   high operator value.
2. **Add `delegated_jobs` retention** (`[delegate] retain_recent_k`
   + cleanup in `_apply_migrations`). Currently unbounded growth.
3. **Continue routes split**: extract `routes_network.py` next.
4. **JobWorker multi-worker concurrency** (`[delegate] worker_count`).

Recommended: **(1) + (2) bundled as v23.0.0a2** (operator-visible
defaults + storage hygiene). Routes-split resumes at v23.0.0a3.

## Operator-facing note

After upgrading to v23.0.0a1:

- **No new endpoints, no removed endpoints, no signature changes.**
  Smoke check is `curl /api/health` + verify version flip.
- The `/jobs` page + 4 `/api/delegated-jobs*` endpoints behave
  identically to v22.2.0.
- If something *does* break that worked in v22.2.0, the bisect
  surface is small: just the import + register call in `routes.py`
  and the new `routes_jobs.py`. Roll back v23.0.0a1 cleanly with
  `git revert <sha>`.

After upgrade: standard `launchctl kickstart -k gui/$(id -u)/com.harbormaster.{ui,mcp}`.

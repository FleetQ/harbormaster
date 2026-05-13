# Sprint Retro — Harbormaster v24.0.0 (GA)

**Date:** 2026-05-13
**Theme:** "Make all remaining". Seven alphas in one day closing
out the v22+v23 carry-over backlog: multi-worker JobWorker,
auto_commit parameter, max_turns UI hints, budget-routes split,
two template splits, and a FleetQ Bridge completion publisher
that closes the harbormaster↔FleetQ push loop end-to-end via a
cross-project async delegation that ran in parallel with the
harbormaster-side work.

## Tags published

| Tag | Type | Capability |
|-----|------|------------|
| v24.0.0a1 | feat | Multi-worker JobWorker (`[delegate] worker_count`) + Tier 1 housekeeping |
| v24.0.0a2 | feat | `auto_commit` parameter on delegate_task (writes + commit in same delegation) |
| v24.0.0a3 | feat | max_turns sizing-guideline popover on /jobs page |
| v24.0.0a4 | refactor | Extract `routes_budgets.py` (5 endpoints + helpers) + shared `_toml_helpers` |
| v24.0.0a5 | refactor | dashboard.html template split — reembed panel into `_partials/_reembed_panel.html` |
| v24.0.0a6 | refactor | project_detail.html template split — Q&A History + Settings tabs into partial |
| v24.0.0a7 | feat | FleetQ Bridge completion publisher (Tier 3 close-out) |
| **v24.0.0** | GA | Drop alpha; arc retro; memory refresh |

8 published versions in the v24 line.

## Numbers (cumulative across v24)

- 8 ships on dedicated feature branches, all fast-forward merged to
  main
- 2013 → **2049 tests** (+36 net across the v24 arc)
- mypy --strict + ruff clean (73 → 76 source files, +3 new modules:
  `fleetq/completions.py`, `routes_budgets.py`, `_toml_helpers.py`)
- 0 backwards-incompatible MCP / HTTP surface changes
- `routes.py`: ~2340 (post-v23) → **~1900 LOC (-440)** via the
  budget-routes extraction. Cumulative across v23 + v24:
  3064 → ~1900 (-1164, **-38%**).
- `dashboard.html`: 3064 → **2787** (-277, via a5)
- `project_detail.html`: 1964 → **1737** (-227, via a6)
- 8 test files patched with `_expand_includes` helper for the
  template-split source-grep pattern

## Capability surface (12 MCP tools + 2 MCP resources + 4 new config knobs)

```
MCP tools (no change in count from v23):
  list_projects   list_hosts   project_status   ask_project
  fan_out_ask     recall_qa    project_graph
  delegate_task   ← v24.0.0a2: + auto_commit param
  get_delegated_task        recall_pending_results
  await_delegated_task      await_inbox

MCP resources:
  harbormaster://jobs/recent       harbormaster://jobs/{job_id}

Config additions (all opt-in):
  [delegate] worker_count = 1                    (v24.0.0a1)
  [fleetq]   publish_completions = false         (v24.0.0a7)
  [fleetq]   team_id = ""                        (v24.0.0a7)
```

## Patterns established (carry forward to v25+)

### `register_*_routes(app, config, render?)` callable seam

5 modules now (jobs, network, dispatcher, history, budgets) follow
the same pattern. Future extractions of remaining surfaces (recall,
plugins, A2A cards, MCP proxy) can copy this verbatim.

### Module-level Pydantic body models

v24.0.0a4's `_ProjectBudgetPutBody` had to move from nested-in-closure
to module-level. FastAPI body-schema introspection treats nested
classes as query parameters, returning 422 on every PUT. Captured as
load-bearing comment + regression-guard test
(`test_put_budget_writes_toml_with_value`).

### `_expand_includes` test helper

For source-grep tests on templates that use `{% include %}`. The
helper KEEPS the include line AND appends the partial content right
after, so both kinds of grep pass. Used by 8 test files; any future
template split that touches grep-tested content should copy this
pattern.

### Block-boundary search heuristic for template splits

`{% block content %}` ... `{% endblock %}` blocks cannot be crossed
by `{% include %}` partials. v24.0.0a6 initially extracted a 1944-
line block that crossed a `{% block inspector %}` boundary, producing
a stray `{% endblock %}` in the partial that Jinja rejected.
**Rule:** when extracting, search for the FIRST `{% endblock %}`
after the section start, never the last.

### Three-gate arm check (v16 carry-forward)

`CompletionPublisher.is_armed()` mirrors `_maybe_writeback_to_fleetq`'s
three-gate pattern: feature toggle + sub-feature toggle + credential
check. Apply this to any future external-write hook.

### Off-thread network IO on JobStore hot path

`CompletionPublisher.publish()` spawns a daemon thread for the POST
so the JobStore worker is never blocked by network latency. Same
pattern any future external sink (Pusher, webhook, third-party
notifier) should follow.

### Cross-project async delegation works end-to-end

The FleetQ-Bridge work was delivered by an async-delegated
sub-agent (~7.5 min run, max_turns=80) that ran in parallel with
the harbormaster-side v24 alphas. Files changed + tests + curl
smoke test + Pusher channel contract all delivered per the
deliverable prompt. v22's async delegate surface is now
production-validated for cross-project work, not just same-process.

## Cool-down day note — broken twice now

The cool-down rule formalised on 2026-05-13 morning said "between
consecutive GA tag lines, schedule one day of zero ship commits".
Today shipped:
- Morning: v22.0.x → v22.1.0 → v22.2.0 (3 ships)
- Afternoon: v22.0.x patch + v23.0.0a1..a5 + GA (7 ships)
- Evening: v24.0.0a1..a7 + GA (8 ships)

= **18 ship commits in one day**, the highest single-day count in
project history. The user-instructed
"директно merge и push" + "make all remaining" overrides the
cool-down rule, which is fine for a one-time push to close the
backlog, but should NOT become the new normal. Tomorrow
(2026-05-14) should be the actual cool-down.

Captured as a v24 retro lesson: the cool-down rule survives if it
remains a default; explicit override is acceptable when the
operator authorises full-backlog-clear.

## v25+ candidates (no longer "deferred" — explicit out-of-scope)

These were on the v23/v24 deferred list and remain out-of-scope —
each requires either external system support or empirical data not
yet available:

1. **Operator-side Pusher subscriber** for `private-harbormaster.{team_id}`
   events — Claude Desktop / agent-side hook to surface
   completion notifications mid-session
2. **Per-call max_turns recommendation engine** based on accumulated
   `delegated_jobs` history — needs 100+ rows of real usage data
3. **More template / route splits** — `dashboard.html` (2787 LOC),
   `project_detail.html` (1737), `network.html` (~1030) all still
   above 1000 LOC; each can follow the v24.0.0a5/a6 pattern when
   they become a friction point
4. **JobStore retention recalibration** — defaults set at
   `retain_recent_k = 1000` in v23.0.0a2 without empirical data
5. **Webhook retry queue** for FleetQ publish failures (currently
   logged + dropped) — only useful if operators report missed events

## Operator-facing upgrade note (v23 → v24.0.0)

After `uv tool upgrade harbormaster-mcp`:

### New surface (all opt-in)

- `delegate_task(..., auto_commit=True)` — subagent runs tests +
  git-commits after edits (with `allow_writes=True`)
- `[delegate] worker_count = N` — multi-worker JobStore concurrency
  (default 1, max 16)
- `[fleetq] publish_completions = true` + `team_id = "<uuid>"` —
  push every async-delegate completion to the FleetQ Bridge relay's
  `POST /api/v1/harbormaster/job-completed` endpoint, which
  broadcasts to Pusher channel `private-harbormaster.{team_id}`
  event `delegate-job-completed`
- `/jobs` page: `?` button next to the counter strip toggles
  max_turns sizing guidance

### What's NEW for source readers

- `routes.py`: 2340 → ~1900 LOC. 5 endpoints + helpers + shared
  TOML serializer moved out
- `routes_budgets.py` (new): the 5 budget endpoints
- `_toml_helpers.py` (new): shared `toml_value(v)` serializer
- `fleetq/completions.py` (new): FleetQ completion publisher
- `_partials/_reembed_panel.html` (new): dashboard reembed UI
- `_partials/_project_detail_qa_and_settings.html` (new): project
  detail Q&A + Settings tabs
- `delegated_jobs` schema gains an `auto_commit` column (idempotent
  migration on JobStore open)

### Standard verification after upgrade

```bash
launchctl kickstart -k gui/$(id -u)/com.harbormaster.ui
launchctl kickstart -k gui/$(id -u)/com.harbormaster.mcp
curl -s http://127.0.0.1:7531/api/health   # version=24.0.0
curl -s http://127.0.0.1:7531/api/delegated-jobs/summary
```

Existing TOML configs unaffected — every new key defaults to off /
1 / "" (same shape as v23 defaults).

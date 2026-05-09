# Sprint Retro — Harbormaster v2.1.0a5

**Date:** 2026-05-09
**Theme:** Two more operator surfaces ride the v2.1.0a4 SSE pattern.
Delegate form lives next to the ask form on each project detail page;
fan-out lands as its own page at `/tools/fan-out`. Cross-project
parallel queries finally have a UI.

## What landed

| SHA | Subject |
|-----|---------|
| (squash) | feat(ui): delegate_task form + fan-out page (#27) |

## Capabilities

### 1 · `_partials/delegate_form.html`

Mirrors the ask form pattern with a structured `deliverable`
textarea — separate "what should the response look like" input.
Same SSE consumer, same AbortController-wired stop button. Renders
on the project detail page right under the ask form.

### 2 · `GET /tools/fan-out` + `templates/fan_out.html`

New top-level page. Project chips populated from
`discover_projects()`, all/none quick toggles, single question,
configurable max_concurrency (default 5) and max_turns (default 3).
Optional `host` filter populated from `[hosts.*]` config.

Submits via JSON mode (not SSE — `fan_out_ask` falls through to
the heartbeat path on the SSE side, so the server returns one
aggregated text payload). Renders the per-target sections in a
single `<pre>` block.

### 3 · Nav addition

`base.html` nav strip now includes `/tools/fan-out` between
"Dashboard" and the JSON endpoints.

## Real numbers

- 1 PR opened / merged (#27)
- 4 new tests
- Test suite: 545 → **549 pass, 1 skip**
- mypy --strict: 46 source files clean
- ruff: clean
- Backwards-incompatible changes: 0
- Lines changed: +352 / -3

## What worked

- **Reusing the SSE consumer pattern.** delegate_form.html is
  basically a clone of ask_form.html with an extra textarea.
  Pasting that pattern is faster than abstracting a partial-of-a-partial,
  and the diff between the two files is small enough that future
  bug fixes will be easy to keep in sync.

- **Fan-out via JSON mode (not SSE).** fan_out_ask doesn't emit
  per-token chunks — it emits one big result. Using JSON mode
  saves the SSE consumer code on the page and matches what the
  server actually does. Less code, exactly the right behaviour.

- **all/none toggles for project chips.** With 50 projects, manually
  checking each is tedious. The two extra buttons take 4 LOC and
  save the user 50 clicks.

## What to change / next

- **Per-target progress indicator on fan-out.** Right now the user
  stares at "…" until the whole batch returns. A per-project status
  list (running/done/error) would help when concurrency is low.
- **Fan-out result not paginated.** With 10+ targets, the aggregated
  output is a wall of text. Could split into collapsible per-target
  sections client-side. Defer.
- **No save / share state.** Fan-out parameters reset on reload.
  URL-encoded query state would be a nice add.

## Action items for the next sprint (v2.1.0a6)

1. **Trajectory history view.** /projects/{name}/history page (or
   inline section on detail). New
   `GET /api/trajectories?project=&host=&limit=` endpoint reading
   from QAStore. Collapsible Q&A pairs sorted by created_at desc.

## Out-of-scope (still)

- Tauri / Electron desktop UI wrapper
- Per-target streaming on fan-out
- URL state encoding for forms
- Headless browser tests

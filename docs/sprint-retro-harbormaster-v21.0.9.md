# Sprint Retro — Harbormaster v21.0.9 (patch)

**Released:** 2026-05-12
**Type:** Patch — friendly empty-states on three `/network` surfaces
**Branch flow:** Directly on `main`

## Why this patch exists

Operator report on 2026-05-12 (third patch on this day, after
v21.0.7 and v21.0.8): visiting `/network#tab=timeline` on a fresh
deployment with 0 MCP calls in the last hour produced three
"looks-broken" surfaces:

- **Inspector (right sidebar)** showed a three-section grid full of
  zeros and the strings "no calls in window" / "no projects active"
  — no explanation of why or how to investigate.
- **Timeline tab (main panel)** rendered the SVG bar chart with all
  60 zero-height bars when events existed but none fit the selected
  1h window. Empty rectangle, no copy.
- **Stats tab (main panel)** rendered the 5-cell summary grid with
  literal 0 / 0% values and three unlabelled empty cells where the
  by-tool / by-source / top-projects lists would normally live.

Existing surfaces (chat-view empty state, recall, fan-out, etc.)
all use the canonical `_partials/_empty_state.html` pattern. The
three above were oversights — they tested the wider
`events.length > 0` / `stats` truthiness rather than the in-window
zero-case.

## Fix shipped

### Timeline in-window empty-state

`templates/network.html` — the SVG and counters footer are now
gated on `timelineEventsTotal > 0`. When the in-window total is 0,
a clear empty-state takes their place with copy that distinguishes
two failure modes:

- **On 1h window:** "No events in the last hour. Switch to a wider
  window to see older traffic." + a "Switch to 24h" CTA button that
  bumps `timelineWindow` directly.
- **On 24h window:** "No events in the last 24h. Run an MCP tool
  against a project to populate the timeline."

`data-empty-state="network.no-events-in-window"` slot taxonomy
matches the existing `network.no-events` (zero-events-at-all)
pattern. Both can co-exist — the outer `network.no-events` covers
"never any traffic", the inner one covers "had traffic but not in
this window".

### Inspector empty-state

The Inspector right-sidebar block used to render its three sections
(Last 1h / By tool / Top projects) unconditionally — when
`total_calls=0` the result was three rows of zeros plus two "(none)"
labels. v21.0.9 wraps the three sections in
`<template x-if="!stats || stats.total_calls > 0">` and shows a
single explainer when `stats.total_calls === 0`:

> No MCP calls in the last hour.
> Inspector pins a 1h rolling window. Widen the main stats panel
> below (last 24h / 7d / all time) to see longer-range traffic, or
> run an MCP tool against a project to populate the feed.

`data-empty-state="inspector.no-recent-traffic"`.

### Stats tab empty-state

Same shape as Inspector: the 5-cell `<dl>` grid is hidden when
`stats.total_calls === 0` and a new explainer block takes its
place. Copy reflects the currently-selected window so the operator
sees a useful message in every state (1h / 24h / 7d / all):

> No MCP calls in the **last 24h** [or **recorded history** when
> window=all].
> Try a wider window using the selector above, or ask a project
> something via your MCP client to populate stats.

`data-empty-state="stats.no-traffic-in-window"`.

## Architectural notes

This is purely template-side — Python source is unchanged. The
`networkInspector()` and `networkStats()` Alpine factories already
expose the boolean predicates we needed (`stats?.total_calls`,
`timelineEventsTotal`).

The patch deliberately stays inside `network.html` even though the
file is now ~1030 LOC (over the 250 LOC partial guideline in the
`ui-v2.1-architecture` memory). Splitting it is queued as a
separate v22 architecture sprint — bundling that into a UX bugfix
patch would have inflated diff and risked breaking 1900+ pinned
tests.

## Verification

- `ruff check src/ tests/` — clean
- `mypy --strict src/harbormaster/` — clean (59 source files)
- `pytest tests/` — **1935 passed** (+7 vs v21.0.8), 1 skip, 0
  failed
- New tests pin:
  - `data-empty-state="network.no-events-in-window"` markup present
  - Timeline SVG hidden when `timelineEventsTotal === 0`
  - Distinct copy for 1h-stuck vs 24h-empty cases
  - "Switch to 24h" CTA bumps `timelineWindow` directly
  - Inspector empty-state visible markup + grid hidden when
    `total_calls === 0`
  - Stats tab empty-state visible markup + 5-cell grid hidden when
    `total_calls === 0`
  - Dynamic window label in the Stats empty-state copy

## /ui-ux-review audit summary

Done as part of the same operator ask. Beyond the three issues
fixed above, the audit found:

- **Architectural debt (deferred to v22):** `dashboard.html` is
  3064 LOC, `project_detail.html` is 1964 LOC, `network.html` is
  ~1030 LOC after this patch — all far over the 250 LOC partial
  guideline. Splitting them is a separate sprint.
- **Mobile timeline:** the SVG uses a fixed `60 * 8 = 480px`
  minimum width via `viewBox`. On phones the bars get squashed.
  Lower priority — deferred.

All other `_empty_state` usages (13 sites across 5 templates) are
clean and follow the canonical partial pattern.

## Operator playbook (new in v21.0.9)

Visit `/network` on a fresh / quiet deployment:

- Timeline tab on 1h with no recent traffic → see the "Switch to
  24h" button and click it; older traffic from the day appears.
- Inspector right sidebar shows the explainer instead of a wall of
  zeros — no more "is my dashboard broken?" moment.
- Stats tab on `1h`/`24h`/`7d`/`all` shows the matching empty-state
  copy when there's nothing in the selected window.

## Chain status

Still HALTED on the v21 base. v21.0.9 is the ninth operator-
initiated patch since v21.0.0, and the third on 2026-05-12 (after
v21.0.7 debug-forensics and v21.0.8 lazy-fetch full-request).

## Lesson captured

Empty-state coverage is not "show empty-state when `data === null`"
— it's "show empty-state any time the surface would otherwise
render a confusing zero or blank". For aggregate / time-window
surfaces specifically, the predicate must distinguish at least
three cases: (a) data not loaded yet, (b) data loaded but the
window is empty, (c) global zero (never any data). The chat tab
got this right in v10; Inspector / Timeline / Stats had been
shipping with only the (a) and (c) cases handled.

Quick rule: if a surface accepts a time-window selector, write the
empty-state at the *window-result* level, not at the *dataset*
level. Otherwise the dashboard looks broken every time the window
is genuinely quiet.

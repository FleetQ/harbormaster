# Sprint Retro — Harbormaster v2.1.0a6

**Date:** 2026-05-09
**Theme:** Last v2.1 alpha. The ask → record → recall loop closes
on the project detail page — every project gets a collapsible
"Recent Q&A" feed reading directly from the per-host store. Sets
up v2.1 GA.

## What landed

| SHA | Subject |
|-----|---------|
| (squash) | feat(ui+history): trajectory history view (#28) |

## Capabilities

### 1 · `QAStore.list_recent(project, limit)`

New public method on the store. Returns `list[QAMatch]` ordered by
`created_at DESC, id DESC` (id is the deterministic tiebreaker for
same-second inserts). Score is set to 1.0 — uniform shape with
`recall()` results so callers render identically.

### 2 · `GET /api/trajectories?project=&host=&limit=`

Soft-fail wrapper. Returns `{enabled: false, message: ...}` when
history is off / extra missing / store fails to open. Limit clamped
to [1, 200]. Same shape pattern as `/api/recall` and
`/api/bridge/status` — the dashboard learned to render this shape
in v2.1.0a3.

### 3 · "Recent Q&A" section on project detail

Below the delegate form. Each row is a collapsible Q&A pair with
truncated question + tool name + relative timestamp in the header.
Limit input lets the user tune visible depth (default 20).
Helpful empty-state message points back at the ask/delegate forms
when no records exist yet.

## Real numbers

- 1 PR opened / merged (#28)
- 5 new tests
- Test suite: 549 → **554 pass, 1 skip**
- mypy --strict: 46 source files clean
- ruff: clean
- Backwards-incompatible changes: 0
- Lines changed: +310 / -5

## What worked

- **Stable secondary sort.** Same-second inserts kept flaking the
  order test until I added `id DESC` as the tiebreaker. Cheap fix,
  expensive lesson — any chronological list with sub-second cadence
  needs a deterministic tiebreaker.

- **Soft-fail uniformity.** Three v2.1 endpoints — recall,
  trajectories, bridge status — share the same `{enabled: bool,
  message: str}` shape. The dashboard's amber-text "message" handler
  works the same way for all three. Future endpoints should mirror
  this.

- **Collapsible rows.** Truncated header keeps the list scannable;
  click-to-expand reveals the full Q&A. ~10 LOC of Alpine state
  per row, no JS framework needed.

## What to change / next

- **No "Refresh" button.** Page load fetches once. After running
  the ask form, the trajectory section is stale until reload. A
  custom event from the ask form firing into the trajectory list
  would be nicer.
- **No deep-link to a specific row.** `#trajectory-{id}` anchors
  would help users share a particular Q&A.
- **No copy-button for the answer.** Trivial follow-on.

## Action items for the next sprint (v2.1.0 GA)

1. **Drop the alpha. Tag `v2.1.0`.** No new code — version bump,
   final retro at `docs/sprint-retro-harbormaster-v2.1.0.md`,
   README status update. Mirrors v1.0.0 / v2.0.0 GA flow.

## Out-of-scope (still)

- Tauri / Electron desktop UI wrapper
- Cross-section communication ("ask form → trajectory refresh")
- Deep-link anchors per-row
- Headless browser tests

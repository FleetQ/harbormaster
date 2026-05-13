# Sprint Retro — Harbormaster v24.0.0a3

**Date:** 2026-05-13
**Theme:** Surface the v22.0.1 empirical `max_turns` guideline on
the `/jobs` page. Collapsible "?" popover next to the counter strip;
table of task-shape → max_turns ranges plus the failure-mode signal
(`exit_nonzero: claude -p exit 1: (no stderr)` ≡ `max_turns_reached`).

## What landed

| File | Subject |
|---|---|
| `src/harbormaster/ui/templates/jobs.html` | new `?` button + collapsible `#max-turns-hints` panel; new `hintsOpen` Alpine state |
| `src/harbormaster/__init__.py` | 24.0.0a2 → 24.0.0a3 |
| `docs/sprint-retro-harbormaster-v24.0.0a3.md` | this file |

## Numbers

- 3 files modified. ~45 net LOC (HTML + Alpine state field).
- 2023 → 2023 tests (unchanged). mypy --strict clean. ruff clean.

## Design notes

### Pure HTML/Alpine — no API change

Zero backend changes. The guideline is static content embedded in
the template. Operator sees the same data the
`incident-playbook` Serena memory has documented since the
v22.0.1 retro. Now it's on the dashboard at delegation time
instead of buried in memory.

### Collapsible by default

`hintsOpen: false` initial state, `x-cloak` to avoid FOUC. Operator
opens with `?` only when they need the reminder — matches the
keyboard-shortcut popover pattern from v6.0.0a4. ARIA: `aria-expanded`
toggles + `aria-controls` ties the button to the panel id.

### Sizing matches existing dashboard conventions

`<ul class="grid grid-cols-1 sm:grid-cols-2">` — same layout style
as the v6.0.0a4 keyboard help popover. `<code>` tokens highlight the
operator-touchable knobs (max_turns, timeout_local). No icon
dependencies (uses `?` glyph directly, same as other buttons in this
template).

## Carry-over

- v24.0.0a4: extract routes_budgets.py
- v24.0.0a5: dashboard.html template split (conservative)
- v24.0.0a6: project_detail.html template split (conservative)
- v24.0.0a7: FleetQ webhook subscriber
- v24.0.0 GA

## Operator-facing note

Visit `/jobs` and click the `?` button next to the counter strip.
The guideline expands inline. Same content as
`incident-playbook` Serena memory entry #1 — kept in sync by
convention (operator-config-reference parity check doesn't cover
prose docs; rely on the retro trail for future updates).

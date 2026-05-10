# Sprint Retro — Harbormaster v16.0.0a3

**Date:** 2026-05-10
**Theme:** Tour wizard hardening — replace fragile CSS-selector
anchors with explicit `data-tour-step` markup attrs, then extend the
tour discipline to the `/network` page.

## What shipped

- **`data-tour-step="N"` markup attrs on dashboard tour anchors**
  (carry-over #6). The five v15.a6 anchors (KPI strip, sidebar,
  ask-form, palette, memories) now carry explicit
  `data-tour-step` attributes. A new `_findAnchor(step)` helper in
  the dashboard tour looks up `[data-tour-step="X"]` first; the
  v15.a6 selector survives as a `legacy:` field so a template
  refactor that drops the attr falls through to the old behaviour
  instead of silently breaking the step.
- **Network page tour wizard** (carry-over #8). Three-step
  walkthrough on first `/network` visit (graph view, filter
  dropdown, timeline toggle), gated by the separate
  `localStorage['hm-network-tour-completed']` key so it doesn't
  collide with the dashboard tour. Same `?tour=1` re-trigger flag
  as the dashboard tour so operators only need to remember one URL
  hint. Anchors via `data-tour-step="network-graph"`,
  `network-filter`, and `network-timeline`.

## Numbers

- **Tests**: 1544 → 1553 (+9 net new)
- **Source files**: 57 (unchanged — extensions only)
- **Wall-clock**: ~25 min
- **Commits on main**: 1 feature merge
- **Lint / type**: ruff clean, `mypy --strict` clean
- **Backwards-incompatible changes**: 0
  - The dashboard tour still works for any operator who upgraded
    in mid-session (legacy fallback selectors live).
  - The network tour is brand-new; no prior contract to violate.
- **Confirmation: did NOT touch `.github/workflows/*`** — yes.

## What worked

- **Two anchor lookup paths, picked in order.** The
  `_findAnchor()` helper hides the legacy fallback inside one
  function, so the rest of the tour reads as if `data-tour-step`
  is the only mechanism. Future cleanup (drop `legacy` field
  entirely) is one delete-key away.
- **Separate localStorage key per tour.** Allowed the network
  tour to ship without a dashboard-tour reset. Operators who
  already dismissed `hm-tour-completed` still see the network
  tour on first `/network` visit.
- **CWD discipline held.** All Bash calls in this phase ran from
  the worktree CWD without explicit `cd`. Discipline lapses for
  v16.a3: **0**.

## What to change for the next phase

- v16.a4 covers diff/comparison viz polish — cross-host config
  diff side-by-side HTML format (#10) + N-way reembed sparklines
  (#11). The sparkline approach (vendored ~50-line SVG roll-our-
  own, no new CDN) keeps with the no-new-deps invariant.

## Notes for v16.a6 split decision

Backend instrumentation (the risky part) hasn't started yet.
Decision deferred to a6 itself.

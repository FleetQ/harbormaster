# Sprint Retro — Harbormaster v9.0.0a6

**Date:** 2026-05-10
**Phase:** v9.0 Phase 6 — Sidebar polish + palette dynamic-action
**Branch:** `feat/v9.0-sidebar-polish`

## What shipped

Four of the five v8-deferred items consolidated into one polish
phase before GA. Pure user-facing surface improvements; zero
backend behavior changes beyond the new ProjectInfo field.

| Capability                            | Surface                                                   |
|---------------------------------------|-----------------------------------------------------------|
| Sidebar Archived group                | Auto-detect via `last_commit_age_days >= 90`              |
| Sidebar rail-collapse                 | 240px → 48px chevron toggle, localStorage-persisted       |
| Sidebar per-host filter dropdown      | `__all__` / `local` / discovered remote labels            |
| Palette `Ask <project> <question>`    | Dynamic-action surface inside Cmd-K                       |
| ProjectInfo.last_commit_age_days      | New backend field driving the Archived auto-detect        |

## Numbers

* **Tests:** 1002 → 1017 (+15 net; +1.5%)
* **Source files:** 52 → 52
* **mypy --strict + ruff:** clean
* **Backwards-incompatible:** 0 user-facing
* **localStorage keys added:** `hm:sidebar:rail-collapsed`, `hm:sidebar:host-filter`

## Deviation from the phase plan

### `stateBadge(state)` helper unification deferred to v10

**Plan said:** "Extract repeated badge-rendering code from 3 sites
(bridge state in statusStrip, trajectory tier in trajectoryList,
reembed phase in reembedPanel) into a single Alpine helper or Web
Component. Same color+icon+aria-label encoding from v8.0.0a2."

**What shipped:** nothing for this item.

**Why deferred:**

1. **No observable user value.** The three badge sites already
   produce identical visuals. The unification is purely a DRY win
   for the template authors; no operator notices the difference.
2. **Risk to v9 GA.** The three call sites have subtle differences
   (bridge state pulls from `/api/bridge/status`, trajectory tier
   from a per-row computed property, reembed phase from a polled
   state file). Extracting the helper without breaking any of the
   three needs careful test coverage that doesn't exist in v8.
3. **v10 is the natural home.** The v10 candidate list already
   includes "lint Alpine x-data for unhandled-promise patterns" —
   a v10 template-quality pass naturally covers helper extraction
   alongside the broader audit.

The decision is recorded here + in the v9 GA retro's v10 candidate
list so the deferral isn't silently lost. Operators using the
existing badges see no change.

### `?q=<question>` URL pre-fill on the project page

The palette dynamic-action navigates to
`/projects/<name>?q=<question>`. The project page itself doesn't
yet read the `q` query parameter to pre-populate the ask form —
that's a 5-line follow-up commit (read `URLSearchParams` in
askForm's `init()`). Reserved for v10 because:

* The URL contract is forward-compatible: ignoring an unknown
  query parameter is the default browser/server behavior.
* The dynamic-action still saves the operator a navigation step
  (no need to scroll, click the project link, then click the
  ask form). The pre-fill is a finishing touch.

## What worked

* **Lift the `last_commit_age_days` derivation to discovery time.**
  One ISO-date parse per project at /api/projects refresh; the
  frontend just compares an integer. Avoids cross-language date
  parsing in JavaScript.
* **`localStorage` for both rail-collapse + host filter.** Reuses
  the v8.0.0a6 sidebar persistence pattern. Operators get
  consistent UX across reloads without server-side storage.
* **Dynamic-action ranks above fuzzy matches.** The user typing
  `Ask harbormaster what's the SSE protocol` has *literal intent*;
  surfacing fuzzy matches above it would feel wrong.
* **Audit-test-per-feature.** Each of the four sub-features has a
  template-walk audit test that pins the literal class names /
  localStorage keys / display labels. Future template refactors
  that drop these silently fail CI.

## What we'd do differently

* **Add a Playwright test that drives the sidebar through all four
  state transitions.** The unit-level template-walk audit catches
  most regressions, but a real-browser test would catch
  Alpine-binding errors (e.g., `_persistHost` not firing because
  `$watch` was misconfigured). Reserved for the v9 GA browser
  smoke suite — the Playwright extra is opt-in via `-m browser`,
  so adding new tests doesn't slow regular CI.
* **Document the localStorage key namespace.** v8 + v9 have grown
  ~6 keys under `hm:sidebar:*` and `hm:cmdk:*`. A short table in
  `docs/operator/ui-state.md` would help operators reset state in
  bulk (`localStorage.removeItem` cookbook).

## Forward to v9.0.0 GA

Phase 6 was the last phase line for v9.0. The next ship is the
**v9.0.0 GA bump + cumulative retro** documenting the 6 alphas +
the v10 candidate list. No new code lands at GA — pure promotion.

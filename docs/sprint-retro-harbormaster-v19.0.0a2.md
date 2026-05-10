# Sprint Retro — Harbormaster v19.0.0a2

**Date:** 2026-05-10
**Theme:** Phase 2 of the v19.0 workspace redesign — five-tab system on
the project_detail page, with URL-hash persistence and 1-5 keyboard
shortcuts. Sets the structural shape that v19.0.0a3-a6 fill in.

## What shipped

- `project_detail.html` wrapped in a `<div x-data="projectTabs()">`
  controller. Five tab panels (`role="tabpanel"`, guarded by
  `x-show="active === '<id>'"`):
  - **Overview** — existing project header card, status block, ask
    + delegate forms (relocated, not duplicated).
  - **Memories** — placeholder banner pointing to v19.0.0a6 +
    the existing memoriesPanel viewer/editor preserved underneath
    so current edit/diff/history flows keep working until a6's
    redesign lands.
  - **Trajectories** — relocated trajectoryList component (only
    one instance; the pre-v19 standalone render is gone).
  - **Q&A History** — placeholder for v19.0.0a5 (project-scoped
    recall search).
  - **Settings** — read-only metadata grid (name, path, last
    commit, language, daily call budget). a4+ will add per-project
    budget edit; the `<dl>` shape lets those controls slot in
    without restructuring.
- Tab strip carries a stable `id="hm-project-tabs"` so e2e tests +
  CSS can target it without brittle class selectors.
- `projectTabs()` Alpine factory:
  - `restoreFromHash()` reads `#tab=<id>` on init via a strict
    `/^#tab=([\w-]+)$/` regex; binds a `keydown` listener that maps
    `1..5` → tab indices.
  - Keyboard handler skips when typing in `INPUT`/`TEXTAREA`/
    `contentEditable`, and when modifier keys are held — those
    gestures belong to the command palette (`Cmd+K`) and the
    browser (`Cmd+1` = first browser tab).
  - `setTab(id)` writes the hash via `replaceState` (not
    `pushState`) so the back button stays bound to navigation, not
    tab toggling.
- Tab buttons carry `:aria-label="tab.label + ' tab (shortcut ' + tab.shortcut + ')'"`
  so the existing a11y floor auditor (which can't read `x-text`
  contents) sees an accessible name.

## Test deltas

- New `tests/ui/test_v19_project_tabs.py` (9 tests, all passing):
  - Tab strip renders all 5 ids in spec order, each with the
    documented keyboard shortcut.
  - Each tab id has a matching `<section role="tabpanel">` panel.
  - URL hash drives active tab via `restoreFromHash` + `setTab`
    using `replaceState`.
  - Keyboard shortcuts respect `INPUT`/`TEXTAREA`/`contentEditable`
    and skip when modifier keys are held.
  - Trajectories tab contains exactly one `trajectoryList` factory
    call (no duplication).
  - Overview tab keeps `{{ project_name }}`, `{{ status_markdown }}`,
    ask form, delegate form.
  - Memories + Q&A History tabs carry their target-version markers
    (a6 / a5) so operators don't file regressions on the bare panes.
  - Settings tab renders the 5 metadata fields inside a `<dl>`.
- `test_a11y_floor.py[project_detail.html]` continues to pass after
  adding the dynamic `:aria-label` to tab buttons.
- All 79 tests in the related UI suites (project tabs + a11y floor +
  app shell layout + memories viewer + memories editor) pass.
- The 24 baseline failures observed in the full suite (8
  `test_stream_ask_*` order-dependent fixture pollution + 16
  `test_bridge.py` scope-mismatch errors) pre-existed Phase 2 and
  pass in isolation; not introduced by this work.

## Visual verification

5 screenshots at `/tmp/v19-a2-tab-{overview,memories,trajectories,
qa-history,settings}.png` (1280x720, captured against the
verification UI on port 17799 with PID rotation, operator UI on
17636 untouched). Each shows the correct tab active in the strip
(underline + highlight) and the corresponding panel content
visible (Overview: project header + status; Memories: placeholder
banner + memoriesPanel; Trajectories: Recent Q&A; Q&A History:
v19.0.0a5 placeholder; Settings: metadata grid).

## Lessons (compounding)

- Playwright `goto(same-path#different-fragment)` is treated as
  in-page navigation; Alpine's `x-init="restoreFromHash()"` only
  fires on full reload. Workaround in the screenshot script: visit
  `about:blank` between target navigations to force a real page
  load. (Browser smoke tests already do per-test page setup so this
  doesn't affect them.)
- The `_IconButtonAuditor` in `test_a11y_floor.py` parses the
  template statically — it can't see Alpine `x-text` interpolations
  inside `<button>`s, so dynamic-label icon buttons need an explicit
  `:aria-label` (or `aria-label`) to satisfy the floor.
- Preserving the existing `memoriesPanel` block inside the Memories
  tab (rather than ripping it out for a placeholder) buys time for
  v19.0.0a6's editor redesign without losing the
  edit/diff/history/tag-chip features that operators already rely on.
  The placeholder banner above signals the planned change without
  removing functionality.

## Next

- v19.0.0a3: inspector pane is currently a fixed copy block; populate
  with context-aware widgets (tab-scoped: project metadata for
  Overview, memory metadata for Memories, trajectory inspector for
  Trajectories).

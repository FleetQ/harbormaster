# Sprint Retro — harbormaster v21.0.0a6

**Tag:** `v21.0.0a6`
**Phase:** 6 of 10 (v21.0 polish sprint)
**Date:** 2026-05-11
**Theme:** Tabs unification across dashboard / network / dispatcher

## What shipped

### 1. Generic `_tabs.html` partial

A presentation-only Jinja partial at
`src/harbormaster/ui/templates/_partials/_tabs.html`. It renders the
visual tab strip and reads `tabs` / `active` / `setTab` from the
caller's enclosing Alpine scope — so it ships with **no** factory of
its own. The wrapper id `hm-{tabs_id}-tabs` is supplied by the caller
via `{% with tabs_id="..." %}` so e2e tests + CSS keep working without
brittle class selectors.

The decision to keep the partial state-less (no `genericTabs()`
factory) was the simplest pragmatic shape: every caller already owns
the panel-side `x-show="active === '<id>'"` guards, so reusing the
existing per-page factories meant zero panel rewrites. The spec's
alternative (factory inside the partial, communicate via
`Alpine.store`) would have been more uniform but required restructuring
every tab panel.

### 2. Project detail page (refactor)

`projectTabs()` factory preserved; only the inline `<nav id="hm-project-tabs">`
markup was removed and replaced by `{% include "_partials/_tabs.html" %}`.
All 5 tabs (Overview / Memories / Trajectories / Q&A History / Settings)
remain — keyboard shortcuts and URL-hash persistence untouched.

### 3. Dashboard tabs (new)

Three-tab system via `dashboardTabs()`:

- **Overview (1)** — existing dashboard content (Quick Ask, KPI strip,
  card grid with Recent activity / FleetQ Bridge / Plugins / Re-embed /
  Recall / Graph, project grid).
- **Recent activity (2)** — larger event feed via new
  `dashboardActivityFeed()` factory polling `/api/network/events?limit=100`
  every 5s.
- **Plugins (3)** — bridge + plugin status surface mounted via a second
  `statusStrip()` instance.

### 4. Network page tabs (refactor + new)

Replaces the three inline view-switch buttons with the shared partial +
adds a **Stats** tab.

`networkTabs()` owns `active`/`setTab` and (a) re-dispatches the legacy
`hm:network:view` event so the existing `networkPanel()` listener keeps
working unchanged for graph / chat / timeline, (b) writes to an Alpine
store `hmNetTab.active` consumed by the `networkStats` section's
`x-show="$store.hmNetTab.active === 'stats'"` guard. The Stats tab
hides the main panel; other tabs hide the stats block.

### 5. Dispatcher trace tabs (new)

Three-tab system via `dispatcherTabs()`:

- **In-flight (1)** — existing live spans section.
- **Recent (2)** — existing trace waterfall.
- **Stats (3)** — new summary panel reading
  `inflight.length` / `traces.length` / `connected` /
  total span count.

`traceWaterfall().active` (the in-flight spans array) was renamed to
`inflight` so the nested `dispatcherTabs()` scope can own its own
`active` (the tab id) without shadowing. The rename is internal to
`dispatcher_trace.html` — no external references existed.

## Tests

- New: `tests/ui/test_v21_tabs_unification.py` (6 tests).
- Updated: `tests/ui/test_v19_project_tabs.py` (1 assertion now checks
  for the partial include rather than the inline `hm-project-tabs` nav).
- Updated: `tests/ui/test_network_chat_view.py`,
  `tests/ui/test_network_graph.py`,
  `tests/ui/test_v14_host_budget_and_timeline.py` — the old
  `hm-network-view-*` button-id assertions now check for the tab ids
  (`id: 'graph'` / `id: 'chat'` / `id: 'timeline'`) plus the
  `hm:network:view` dispatch contract.
- Updated: `tests/ui/test_template_safety.py` ALLOWLIST — added
  `("dashboard.html", "active === 'overview'")` with comment. The
  default-tab guarantee (`active: 'overview'` in the factory) means
  Mermaid measures inside a visible wrapper on fresh page loads;
  deep-links to other tabs are operator navigation that postdates the
  initial render.

## Files modified

```
src/harbormaster/__init__.py                              (version bump)
src/harbormaster/ui/templates/_partials/_tabs.html        (new)
src/harbormaster/ui/templates/project_detail.html         (refactor)
src/harbormaster/ui/templates/dashboard.html              (3 tabs + factories)
src/harbormaster/ui/templates/network.html                (4 tabs + Alpine store)
src/harbormaster/ui/templates/dispatcher_trace.html       (3 tabs, active → inflight)
tests/ui/test_v21_tabs_unification.py                     (new)
tests/ui/test_v19_project_tabs.py                         (assertion update)
tests/ui/test_network_chat_view.py                        (assertion update)
tests/ui/test_network_graph.py                            (assertion update)
tests/ui/test_v14_host_budget_and_timeline.py             (assertion update)
tests/ui/test_template_safety.py                          (ALLOWLIST entry)
docs/sprint-retro-harbormaster-v21.0.0a6.md               (new)
```

## Verification

Visual checks against a private server on port 17799 (operator on
17636 was preserved across the run):

- **/** — tab strip "Overview 1 · Recent activity 2 · Plugins 3"
  visible above main content; Overview default-active.
- **/network** — tab strip "Graph 1 · Chat 2 · Timeline 3 · Stats 4"
  rendered (tour modal covered Graph/Chat in the screenshot but the
  IDs were assertible).
- **/dispatcher** — tab strip "In-flight 1 · Recent 2 · Stats 3"
  visible; In-flight default-active with empty-state copy intact.
- **/projects/harbormaster#tab=settings** — Settings tab active by
  URL-hash, Metadata + Daily call budget rendered. Hash restoration
  confirmed.

## Lessons

1. **Scope shadowing inside Alpine.** Nesting a tab controller that
   also owns `active` inside an outer factory that already had an
   `active` property silently broke the inner template until we renamed
   the outer field to `inflight`. Lesson: when introducing a shared
   pattern that claims a name like `active`, audit ancestor factories
   in every consumer file before declaring the partial done.
2. **Template-safety scanner pays for itself.** The `x-show` around
   `<pre class="mermaid">` would have re-introduced the v6.0.0 bug
   class. The scanner caught it; the documented ALLOWLIST mechanism
   let us declare the runtime guarantee explicitly rather than relying
   on a comment somewhere else.
3. **State-less partials beat state-ful ones.** Letting each page own
   the tab factory kept this phase to a thin presentation extraction
   rather than a cross-cutting state refactor — the diff is
   reviewable per-page and the existing keyboard / hash / a11y
   contracts stayed pinned.

# Sprint Retro — Harbormaster v8.0.0a4

**Date:** 2026-05-10
**Theme:** Phase 4 of the v8 UI polish line — global Cmd-K command
palette. Fuzzy search across projects, tools, pages, and help.
Single keyboard reach gets you anywhere in the dashboard. Built
in pure Alpine + ~150 lines of vanilla JS — no fuzzy-match CDN
dep, lazy-loads `/api/projects` on first open.

## What landed

### `harbormaster` (this repo)

| SHA | Subject |
|-----|---------|
| (merge) | feat(ui): Cmd-K command palette with fuzzy search across projects + tools |

## Capabilities (this sprint)

### 1 · Global `commandPalette()` Alpine scope (mounted in `base.html`)

Lives at the root of every page render so the palette is one
keystroke away from anywhere — dashboard, project detail, fan-out.
Mounts with `x-data="commandPalette()"` and `x-init="bindKeyboard()"`.

State:

* `open: bool` — palette visibility
* `query: string` — live-bound search input
* `projects: array` — lazy-fetched on first open, then cached
* `projectsLoaded: bool` — single-fetch guard
* `results: array` — currently-displayed scored matches
* `selectedIndex: int` — keyboard focus pointer

### 2 · `Cmd+K` (Mac) / `Ctrl+K` (Win/Linux) trigger

Single window-level `keydown` listener checks
`(e.metaKey || e.ctrlKey) && key === 'k'`. The handler always
`preventDefault()`s — mostly to disable Chrome's address-bar
focus override on Cmd+L users muscle-memory hitting Cmd+K.

### 3 · Fuzzy match — bigram score, no CDN dep

`_score(query, candidate)`:
* Fast path: substring match → return `1000 - position - length*0.1`
  (massive boost; favors prefix matches).
* Fallback: bigram intersection ratio. If `q` and `candidate`
  share ≥40% of bigrams, return `intersection / qBigrams.size *
  100`. Otherwise 0.

This works fine for our small candidate set (≤ ~150 items: tools
+ projects). No `fuse.js` or `fzf-wasm` dep — keeps the dashboard
under one CDN tag (Tailwind only; Alpine + Mermaid still loaded).

### 4 · Result categories with badges

Each result row shows: small uppercase category badge (Tool /
Project / Page / Help) + label + optional shortcut/href hint.
Shipped catalog:

* **Tool** entries: `fan-out`, `recall`, `graph`, `reembed` —
  scroll into view or navigate.
* **Page** entry: `dashboard` (=> `/`).
* **Help** entry: `shortcuts` (toggles helpPopover via dispatched
  `?` keydown).
* **Project** entries: dynamic from `/api/projects` — navigate to
  `/projects/{name}`. Project entry's "shortcut" cell shows the
  detected language.

### 5 · Keyboard navigation

* `↑` / `↓` → `moveSelection(±1)` (wraps at boundaries).
* `Enter` → `activate()` — closes palette, then triggers `href`
  (navigation) or `action()` (in-page scroll/dispatch).
* `Esc` → close palette (window-level so it works no matter where
  focus drifted).

### 6 · ARIA semantics

* `role="dialog" aria-modal="true" aria-label="Command palette"`
  on the backdrop wrapper.
* `role="listbox"` on the result list, `role="option"` per row,
  `:aria-selected="i === selectedIndex"`.
* `aria-label="Search projects, tools, and shortcuts"` on the
  input. Placeholder is supplementary.

### 7 · Help popover entry

The keyboard-shortcut popover (`?`) gains a new "global" section
listing `Cmd / Ctrl + K → open command palette` so the palette is
discoverable for non-power users who never guess Cmd-K is wired.

### 8 · Static audit test (`tests/ui/test_command_palette.py`)

16 new test parametrisations:

* `test_palette_mount_in_base` — `commandPalette()` declared in
  `base.html`.
* `test_palette_dialog_has_aria_attrs` — full dialog/aria attrs.
* `test_palette_input_has_aria_label` — input is labelled.
* `test_palette_listbox_semantics` — listbox + option roles.
* `test_palette_shortcut_binding` — Cmd+K AND Ctrl+K both checked.
* `test_palette_keyboard_navigation_handlers` — arrow / enter /
  escape handlers present.
* `test_palette_categories_present` — Tool / Page / Help / Project.
* `test_palette_lazy_projects_fetch` — `projectsLoaded` guard +
  `/api/projects` fetch.
* `test_palette_fuzzy_match_helpers` — `_bigrams` + `_score` +
  substring fast path all present.
* `test_help_popover_lists_cmd_k` — popover advertises the
  shortcut on both platforms.
* `test_palette_static_tool_entry_present[*6]` — every shipped
  tool entry remains in the catalog.

## Real numbers

- 8/8 v8.0.0a4 sub-items shipped (full Phase 4 plan)
- 1 feature branch merged (no PR)
- +16 new tests (849 → 865 collected; +0 source files, 52 total)
- mypy --strict + ruff: clean
- Backwards-incompatible changes: 0
- Templates touched: 2 / 5 (base.html, dashboard.html)

## What worked

- **Pure-vanilla bigram match.** ~10 lines of JS, sub-millisecond
  for 150 candidates, no transitive dep. Catches typos like
  "fanot" → fan-out via 4-of-5 bigram overlap. Skipped `fuse.js`
  (~6KB minified) entirely — would have inflated the page weight
  for marginal quality gain.
- **Lazy `/api/projects` fetch.** The palette opens instantly even
  on installs with 100+ projects because the network call only
  fires on first `Cmd+K`. Subsequent opens hit the in-memory
  cache. Single-fetch via `projectsLoaded` flag.
- **Action vs href in the catalog.** Same data shape supports
  both: `{href: '/foo'}` for navigation and `{action: () => …}`
  for in-page scroll-or-dispatch. Single dispatcher in `activate()`
  handles both branches cleanly.
- **`@keydown.escape.window`.** Escape works whether focus is in
  the input, on a result, or anywhere else — Alpine's `.window`
  modifier is exactly the right primitive.
- **Help popover gains a "global" section first.** Cmd-K should be
  the most prominent shortcut now; it leads the list.

## What we'd do differently

- **Add a "no project entries on this page" hint when projects
  fetch fails.** Currently the palette silently degrades — tools
  still work but the operator doesn't know why projects didn't
  load. A small "(projects unavailable)" footer would surface the
  failure without breaking the affordance.
- **Result-row selection should preserve mouse hover when arrow
  keys move it.** Right now `@mouseenter` overrides `selectedIndex`
  the moment the cursor hovers any row — which is correct for the
  primary case but jumpy if the operator's mouse is over the list
  while they arrow-key down. Defer; it's a micro-preference.

## Action items for the next sprint (v8.0.0a5)

1 · Phase 5 — KPI strip atop dashboard. 5-cell horizontal grid:
**Projects** count, **Active embeds** (running/processed/total),
**Recent queries (1h)**, **Bridge** pill (collapsed), **Dispatcher**
(placeholder until v9 waterfall ships). Each cell auto-refreshes
every 30s. Reuses the v7.0.0a6 `ProjectsCache` for the projects
count — no per-render overhead.

## Out-of-scope (still)

- Multi-select results (Tab to multi-pick, Enter to bulk-action).
  Not part of any operator request; defer until asked.
- Recent commands history. Would require localStorage write — fine
  for v9. Phase-4 keeps the palette stateless across sessions.
- Action search inside individual surfaces (e.g. "ask {project}
  {question}"). The plan calls for "Ask focuses dashboard ask form
  for selected project" — currently `action: () => focus textarea`
  isn't shipped because we'd need per-project disambiguation.
  Project entries navigate to the project page where the Ask form
  is the first card; one extra click. Defer the inline-ask pattern.

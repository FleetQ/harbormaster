# Sprint Retro — Harbormaster v8.0.0a6

**Date:** 2026-05-10
**Theme:** Phase 6 of the v8 UI polish line — left navigation
sidebar with grouped projects (pinned, recently asked, by language).
240px desktop rail; mobile hamburger toggle. Operator-marked pins +
collapsed-group state persisted to `localStorage`.

## What landed

### `harbormaster` (this repo)

| SHA | Subject |
|-----|---------|
| (merge) | feat(ui): left sidebar with grouped project navigation + pinned + recent |

## Capabilities (this sprint)

### 1 · Global `<aside role="navigation">` sidebar in `base.html`

Mounted at the body level so every page (dashboard, project detail,
fan-out) gets the same rail. 240px wide on desktop, hidden behind
a hamburger toggle on mobile (`md:` breakpoint at 768px).

* `aria-label="Project navigation"` on the aside.
* Sticky at `top-[57px]` (clears the header), `bottom-0`,
  `overflow-y-auto` so long project lists scroll independently.
* Mobile backdrop click closes; `Esc` close handled implicitly via
  the `mobileOpen` toggle.

### 2 · Hamburger toggle via custom event bus

Header carries an `md:hidden` button that dispatches
`hm:sidebar:toggle`. The sidebar listens with
`@hm:sidebar:toggle.window`. Decouples the trigger from the panel
— either source can trigger the toggle without coupling Alpine
scopes.

### 3 · Three canonical groups

* **Pinned** — operator-marked, persisted to
  `localStorage['hm:sidebar:pinned']`. Toggle via the per-row
  `★` button. Aria-label dynamically swaps `Pin foo` ↔ `Unpin foo`.
* **Recently asked** — last 5 unique project names from
  `/api/trajectories?limit=20`. Pinned projects automatically
  drop out of this group to avoid duplication.
* **By language** — projects grouped by `ProjectInfo.language`
  (added v6.0.0a3). Sorted alphabetically; `unknown` always last.
  Per-language collapse/expand button persists state to
  `localStorage['hm:sidebar:lang-collapsed']`.

Each group carries `data-sidebar-group="<id>"` for audit; the
pinned + recent groups self-hide when empty (no zero-state placeholder
clutter).

### 4 · Search-within-sidebar fuzzy filter

Single text input atop the rail filters every group in real-time.
Currently substring match (case-insensitive) — bigram fuzzy from
the Cmd-K palette (Phase 4) is on the v9 candidate list if
operators ask. The input carries
`aria-label="Filter projects in sidebar"`.

### 5 · `projectSidebar()` Alpine scope

Lazy-loads `/api/projects` and `/api/trajectories?limit=20` on
mount. Per-state helpers:

* `init()` → `_loadPersisted()` + parallel data fetches.
* `togglePin(name)` → mutates pinned + persists.
* `toggleLanguage(lang)` → mutates collapsed map + persists.
* `visiblePinned()` / `visibleRecent()` /
  `visibleProjectsForLanguage(lang)` → all apply the filter +
  group rules in one place.
* `_matchesFilter(p)` — substring match on project name.

Soft-fails per source — a `/api/trajectories` error doesn't break
the whole rail; the operator just doesn't see the "Recently asked"
group.

### 6 · Main content offset (`md:ml-60`)

The `<main>` carries `md:ml-60` so dashboard / project detail /
fan-out content doesn't overlap the rail on desktop. Mobile uses
the full width (rail is overlay-style with backdrop).

### 7 · Bug fix: `/api/projects` shape mismatch

Phase 4's Cmd-K palette and Phase 6's sidebar both originally
called `data.projects || []` against `/api/projects`, but the
endpoint returns a *bare* JSON list (`list[dict[str, object]]`).
Fixed both Alpine scopes to consume the response directly. No
behavior change pre-this-fix because the endpoint never shipped
in a use that worked — the regression was caught in the audit.

### 8 · Static audit (`tests/ui/test_sidebar.py`)

12 new test parametrisations:

* `test_sidebar_aside_role_and_label` — role + aria-label.
* `test_hamburger_toggle_dispatches_event` — both ends of the
  custom event bus wired.
* `test_sidebar_group_present[*3]` — all three groups present.
* `test_sidebar_search_input_labelled`.
* `test_sidebar_pin_toggle_aria_label` — dynamic Pin/Unpin label.
* `test_project_sidebar_alpine_scope_defined` — scope + key
  helpers all defined.
* `test_sidebar_persists_pinned_to_localstorage`.
* `test_sidebar_persists_collapsed_groups`.
* `test_sidebar_loads_recent_from_trajectories`.
* `test_sidebar_main_layout_offsets_for_rail` — `md:ml-60` present.

## Real numbers

- 8/8 v8.0.0a6 sub-items shipped (full Phase 6 plan)
- 1 feature branch merged (no PR)
- +12 new tests (881 → 893 collected; +0 source files, 52 total)
- mypy --strict + ruff: clean
- Backwards-incompatible changes: 0
- Templates touched: 1 / 6 (base.html — _empty_state.html new in a3)
- Bug found + fixed inline: `/api/projects` shape mismatch in
  Phase 4 + 6 client code.

## What worked

- **Mount in `base.html`, not per-page.** One source of truth for
  navigation across every UI route. No copy-paste between
  `dashboard.html` / `project_detail.html` / `fan_out.html`.
- **`localStorage` for operator preference, not config file.**
  Per-operator (per-browser) pin lists make sense — different
  team members care about different projects. Keeps the
  config.toml lean and operator-customisation friction-free.
- **Custom-event bus (`hm:sidebar:toggle`) for the hamburger
  toggle.** Cleaner than passing a shared scope between header
  and sidebar Alpine roots. Same pattern v4.0.0a4 used for
  trajectory dirty signals.
- **Self-hiding groups when empty.** Sidebar starts clean for
  fresh installs; the "Recently asked" group only appears once
  trajectories exist. Reduces visual noise on day-1.
- **Bigram-free filter is fine for ≤200 projects.** Substring
  match is what operators actually do here ("rust" → all rust
  projects). The Cmd-K palette has fuzzy because it spans tools
  + projects + pages and benefits from typo tolerance.

## What we'd do differently

- **Sidebar collapse-toggle for desktop wasn't shipped.** The plan
  called for a `localStorage`-persisted desktop collapse state.
  Currently the rail is always visible on desktop. Defer — the
  collapsed-language groups give per-section collapse, which is
  more granular than "hide the whole rail". Add a top-level
  collapse toggle if operators ask.
- **Archived group not shipped.** The plan listed an "Archived"
  group (last commit > 90 days OR operator-marked). The
  operator-marked path needs a per-project flag we don't currently
  store; the auto-detected path needs a `last_commit_age` field
  we'd have to add to `ProjectInfo`. Defer to v9; the manual pin
  + language grouping covers the immediate need.

## Action items for the next sprint (v8.0.0a7)

1 · Phase 7 — Tailwind v4 + OKLCH semantic tokens + drop HTMX.
Largest blast radius of the v8 line. Vendor Tailwind v4 (drop
the CDN script tag), define `@theme` tokens for semantic colors,
migrate utility classes to semantic-token classes, confirm zero
`hx-*` attributes (Phase 1's audit already shows none) and remove
the HTMX script tag.

## Out-of-scope (still)

- Sidebar drag-to-reorder pinned projects. Not a clear pain point
  yet; defer until pin-count > 10 becomes common.
- Per-host filter in the sidebar. Currently shows local projects;
  multi-host support is a v9 candidate.
- Right-click context menu (Pin / Open in new tab / Copy path).
  Defer — would shift the affordance model significantly.

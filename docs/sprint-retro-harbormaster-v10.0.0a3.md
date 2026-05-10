# Harbormaster v10.0.0a3 — Sprint Retro

**Phase 3 of 8** in the v10.0 alpha chain.

## Shipped

**Full app-shell layout rework** — persistent fixed topbar +
persistent fixed sidebar + scrollable main content + slim fixed
bottom-bar. Plus topbar nav cleanup (operator-flagged useless
links removed).

## Implementation

`base.html`:
- Body: `h-screen overflow-hidden` (was `min-h-screen`).
- Topbar `#hm-topbar`: `position: fixed`, `top-0`, `h-12`. Always
  visible regardless of page scroll. Z-index 40.
- Sidebar `#hm-sidebar`: still `position: fixed` but anchored
  `top-12 bottom-7` so it sits flush under the topbar and above
  the footer-bar. Z-index 30.
- Main `#hm-main`: own scroll context — `position: fixed` between
  `top-12 bottom-7`, `overflow-y-auto`. Switched the rail offset
  from `ml-` (margin) to `left-` (positioning), since main is
  now fixed; offset still toggles `md:left-12` (collapsed) ↔
  `md:left-60` (expanded).
- Footer `#hm-footer`: slim fixed bottom-bar (`h-7`) instead of
  an in-flow footer that scrolled with the page. Z-index 40.

Topbar nav cleanup:
- KEEP: Dashboard / Fan-out / Dispatcher / GitHub.
- REMOVE: `/api/projects` + `/api/health` (operator flagged as
  useless). Endpoints still exist; they're just no longer
  surfaced as user-facing nav links.
- Auth lock indicator added when `auth_token` is present
  (hidden on mobile to keep the topbar slim).

## Tests

New: `tests/ui/test_app_shell_layout.py` — 9 tests:
- Body uses `h-screen overflow-hidden` (sentinel for old
  `min-h-screen` regression).
- Each of the 4 landmarks has a stable id (`hm-topbar`,
  `hm-sidebar`, `hm-main`, `hm-footer`).
- Topbar fixed `top-0` + `h-12`.
- Sidebar fixed `top-12 bottom-7 left-0`.
- Main fixed `top-12 bottom-7` + `overflow-y-auto` + both
  `md:left-` offset variants.
- Footer fixed `bottom-0` + `h-7`.
- Topbar nav keeps Dashboard / Fan-out / Dispatcher.
- Topbar nav drops `/api/projects` + `/api/health` literals.

Updated:
- `test_sidebar.py::test_sidebar_main_layout_offsets_for_rail` —
  `md:ml-60` → `md:left-60`.
- `test_sidebar_v9_polish.py::test_rail_collapsed_offset_main_content`
  — same swap for the conditional binding.
- `test_ui.py::test_root_links_to_api_endpoints` → renamed to
  `test_root_topbar_omits_useless_api_endpoints`. Asserts the
  nav literals are gone while the JS `/api/projects` ref still
  works (sidebar JS uses it).

## Numbers

- Tests: 1023 → 1034 (+11; 9 new layout tests + 2 net from
  renames).
- Source files: 52 → 52.
- mypy --strict: clean.
- ruff: clean.

## Deviations

None. Implemented exactly as specced. The plan flagged Phase 3 as
high-risk (could need an a3.5 split); it didn't — the structural
edits were tightly scoped to base.html and three test files.

## Risks / Follow-ups

- The new fixed-position layout requires the body to be
  `overflow-hidden`. Anything that previously relied on the body
  scrollbar (deep-link anchors with `scrollIntoView`, third-party
  scroll-restoration libs) needs to target `#hm-main` instead.
  Cmd-K palette `scrollIntoView` callbacks already target
  scoped elements via `[x-data^="..."]` selectors — they continue
  to work because the scroll happens inside `#hm-main`.
- Mobile responsive: at <768px the sidebar slides over the
  content via the existing hamburger toggle (unchanged from
  v8.0.0a6); the topbar height stays `h-12` for both.
- Future: a sticky page-level secondary nav / breadcrumbs strip
  could fit between topbar and main without further restructuring
  — slot it as `<header class="sticky top-0 ...">` inside the
  `#hm-main` scroll context.

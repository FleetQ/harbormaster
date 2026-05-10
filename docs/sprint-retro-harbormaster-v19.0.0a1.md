# Sprint Retro — Harbormaster v19.0.0a1

**Date:** 2026-05-10
**Theme:** Foundation phase of the v19.0 workspace redesign — replace
the v10 fixed-shell layout with a 3-column CSS grid (sticky 240px
nav + fluid main + sticky 320px collapsible inspector).

## What shipped

- `base.html` body skeleton rewritten end-to-end:
  - Topbar: `fixed top-0 inset-x-0 h-12 z-50` with brand left, page
    title centered (`{% block page_title %}`), Cmd-K hint + theme
    toggle + auth indicator right.
  - Body grid: `pt-12 grid min-h-screen grid-cols-[240px_1fr_320px]`
    (or `..._0]` when the inspector is collapsed).
  - `appShell()` Alpine factory owns inspector collapse state,
    persisted to `localStorage['hm-inspector-collapsed']`.
  - Floating `»` re-expand button when collapsed.
- New partial `_partials/_sidebar.html` containing the entire
  `projectSidebar()` factory and its DOM (host filter, in-sidebar
  filter, Pinned / Recently asked / By-language / Archived / Ignored
  sections). Base.html now `{% include "_partials/_sidebar.html" %}`
  inside the `{% block sidebar %}` slot.
- Each top-level page now declares `{% block page_title %}<name>{% endblock %}`
  so the topbar middle slot has content. No other page-template
  changes were needed — none of them carried inner `max-w-7xl` or
  `mx-auto p-4` wrappers (those lived in the old `<main>` and were
  retired with it).
- Cmd-K palette gains explicit `/dispatcher` and `/network` tool
  entries to compensate for the dropped topbar nav links.

## Test deltas

- `test_app_shell_layout.py` rewritten for the v19 contract:
  asserts the grid columns, the four landmark ids
  (`hm-topbar`, `hm-sidebar`, `hm-main`, `inspector`), localStorage
  persistence, and that the v10 fixed-footer / `top-12 bottom-7`
  pattern is gone.
- `test_sidebar.py` and `test_sidebar_v9_polish.py` updated to read
  sidebar markup from the partial. Removed assertions tied to the
  retired v9 mobile-hamburger and rail-collapse features (those are
  superseded by the inspector-collapse pattern).
- `test_ignored_projects_endpoint.py` updated for the partial path.
- `test_dispatcher_trace_endpoint.test_dispatcher_page_in_nav` now
  asserts dispatcher reachability via the Cmd-K palette catalog
  (`id: 'dispatcher'` + `href: '/dispatcher'`) instead of a topbar
  anchor — topbar nav links were intentionally retired.
- New browser test `tests/ui/test_v19_three_column_shell.py` (gated
  on the `browser` marker) checks landmark visibility, inspector
  collapse via the in-pane `«` button, and reload persistence via
  localStorage.

## Visual verification

Three screenshots captured against a verification UI on port 17799
(operator's UI on PID 19997 left untouched throughout):

- `/tmp/v19-a1-dashboard.png` — topbar present, sidebar with project
  list (PHP/JS/GO groups + Recently asked), main column with KPI
  strip + Plugins + Auto-reembed, inspector placeholder visible.
- `/tmp/v19-a1-project.png` — same shell on `/projects/harbormaster`;
  sidebar persists, main shows the project status panel, inspector
  empty.
- `/tmp/v19-a1-network.png` — same shell on `/network`; sidebar
  persists, main shows the network filters/KPI cards, inspector
  empty.

All three confirm the 3-column layout renders correctly. The legacy
v16 dashboard tour overlay still fires on first visit — that's
existing behavior, unrelated to this phase.

## Surprises

1. **Jinja parsed `{% block content %}` inside an HTML comment.**
   The first base.html draft had a doc comment that read "per-page
   content goes straight into `{% block content %}` …" inside `<!-- … -->`.
   Jinja doesn't respect HTML comments and tried to open a real
   block, so it never found the matching `endblock`. Fix: switched
   the doc comment to Jinja's own `{# … #}` form. Worth remembering
   any time a base template is rewritten — this would have failed
   the same way at boot.
2. **`uv sync --extra ui-test` removes other extras.** The first
   sync wiped dev/ssh/etc; had to re-run with `--all-extras` to
   restore them before Playwright would import. (No effect on the
   shipped diff — the lockfile re-sync was reverted before commit
   so this PR carries only template + test changes.)

## Non-changes (deliberate)

- **Color and density unchanged this phase.** Spec defers those to
  v19.0.0a4. All `--hm-*` tokens, all `oklch(…)` definitions, all
  Tailwind utility usage in page templates is identical.
- **Per-page inspector content empty.** Spec defers that to
  v19.0.0a3. The right column shows only the "INSPECTOR" header +
  "Context-aware widgets land in v19.0.0a3." placeholder.
- **No CI workflow changes.** Spec called out `.github/workflows/*`
  as out of scope for this phase.
- **Theme toggle, Cmd-K palette, mermaid module, cached_getter +
  tiny_sparkline + state_badge partial includes** all preserved
  byte-for-byte from v18 — the rewrite is layout-only.

## Numbers

- Files touched: 13 (7 templates + 6 tests; 1 new partial + 1 new
  test file + 11 modified).
- Test count: 1634 → 1636 (+2 from the new browser test file's
  collected items).
- Source files: 57 → 57 (no `src/*.py` changes).
- mypy --strict: clean. ruff: clean.

## What's next (Phase 2 — TBD)

The orchestrator is gating on visual verification before authorizing
Phase 2. This sprint stops here per spec.

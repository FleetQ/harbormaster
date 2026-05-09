# Sprint Retro — Harbormaster v3.0.0a7

**Date:** 2026-05-09
**Theme:** Operators can ask any project a question directly from the
dashboard. No navigation required.

## What landed

### `harbormaster` (this repo)

| SHA | Subject |
|-----|---------|
| `a2ba48f` | feat(ui): inline ask form on dashboard cards (v3.0.0a7) |

## Capabilities (this sprint)

### 1 · Per-card "ask" toggle

Each project card grew an `ask` button in the footer. Clicking expands
a collapsible inline form scoped to that card. The form delegates to
the existing `askForm()` Alpine component with
`{ project: p.name, host: 'local' }` from the `x-for` scope.

Cards still link to `/projects/<name>` for the full detail view — the
project-name link is preserved as a normal anchor inside the card
header. Clicking the `ask` button does NOT navigate.

### 2 · Component definition extracted

The `askForm()` Alpine factory used to live inline at the bottom of
`_partials/ask_form.html`. Two pages now need it (dashboard + project
detail), and copy-pasting the ~100-line implementation would have
guaranteed drift.

After: `_partials/_ask_form_script.html` holds the function definition
once. Both `_partials/ask_form.html` (project detail) and
`dashboard.html` `{% include %}` it. Each page gets exactly one
function definition; both surfaces stay synchronised.

### 3 · Mobile-friendly card layout

Card grid keeps its responsive 1/2/3-column layout even when several
cards have their ask form expanded. The result `<pre>` caps at
`max-h-48` with `overflow-y-auto` so a 5000-char answer doesn't blow
out the card height and shove other cards offscreen.

## Real numbers

- 1/1 v3.0.0a6-retro action item shipped
- 0 PRs opened — merged `feat/v3.0-dashboard-ask` directly via `--no-ff`
- 4 new unit tests
- Test suite delta: 611 + 1 skip → **615 + 1 skip**
- `mypy --strict` clean across 48 source files
- `ruff` clean across `src/` and `tests/`
- 0 backwards-incompatible changes — additive UI surface

## What worked

- **Extract the component, not the markup.** The form HTML differs
  between dashboard (compact, 2-row textarea) and project detail
  (full-width, 3-row textarea, more chrome). Sharing the *behaviour*
  (askForm function) without sharing the *layout* gave each surface
  its own visual budget.
- **Card markup restructure was minimal.** Stripping the wrapping
  `<a>` and moving the link to the project-name `<h3>` instead kept
  the rest of the card untouched. The collapsible inline section
  bolts on with no flex-layout reflow.
- **`x-data="{ askExpanded: false }"` per card.** Each card has its
  own toggle state by virtue of being a separate Alpine scope —
  no need to track an array of "open card IDs" globally. Open
  multiple cards at once if you want to.

## What to change / next

- **Inline form duplication.** The dashboard's compact form HTML and
  the project_detail's full form HTML each describe the same
  textarea + buttons + result pre. If we add another ask surface,
  consider one more partial split. Defer until that third surface
  exists.
- **No host selector on the dashboard form.** Dashboard cards default
  `host: 'local'` because per-card "which host?" UI is heavyweight
  for the 95% case where the project is local anyway. Operators who
  need per-host can navigate to project_detail (or use fan-out).
  Acceptable simplification.

## Action items for the next sprint (v3.0.0a8)

1. **Ask→trajectory cross-section refresh events.** When the project
   detail page's ask form completes, the trajectory section below
   doesn't refresh — operators have to F5 to see their just-asked
   question in the history. Wire `Alpine.$dispatch('hm:trajectory:dirty', { project })`
   from the ask form's stream-end path; trajectory partial listens
   via `x-on:hm:trajectory:dirty.window` and re-fetches.

## Out-of-scope (still)

- Tauri / Electron desktop UI — no demand.
- Relay-binary path (Path B) — Path C HTTP tunnel covers it.
- IDE extension — MCP works with any MCP client.
- pnpm v5 lockfile support — pre-2022 format.
- Multi-worker dispatch pool — defer until thread-safety proven.
- Session-cookie auth + CSRF — defer until multi-operator UI is real.
- Per-card host selector — fan-out covers cross-host.

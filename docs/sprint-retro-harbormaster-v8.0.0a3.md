# Sprint Retro — Harbormaster v8.0.0a3

**Date:** 2026-05-10
**Theme:** Phase 3 of the v8 UI polish line — every "nothing yet"
surface gets a canonical 3-part empty state (headline + body + CTA).
Operators stop seeing terse one-line "no matches yet" prose and
start seeing actionable next steps every time the data is empty.

## What landed

### `harbormaster` (this repo)

| SHA | Subject |
|-----|---------|
| (merge) | feat(ui): canonical empty states across all dashboard surfaces |

## Capabilities (this sprint)

### 1 · `_partials/_empty_state.html` — canonical 3-part partial

New shared partial that other templates can include via Jinja `with`:

```jinja
{% with es_headline="No projects discovered",
        es_body="Add an entry to ~/.config/harbormaster/config.toml.",
        es_cta_label="Read the operator guide",
        es_cta_href="…" %}
  {% include "_partials/_empty_state.html" %}
{% endwith %}
```

The slots are: `es_headline`, `es_body`, `es_cta_label`, plus
either `es_cta_action` (for an Alpine `@click=` button) or
`es_cta_href` (for an anchor link). Carries `role="status"` so SR
announces politely and uses the canonical
`border border-gray-800 bg-gray-900/40 ... px-4 py-6 rounded text-center`
container.

### 2 · 5 surfaces converted to canonical empty states

Each carries `data-empty-state="<surface-id>"` for easy auditing:

* `dashboard.no-projects` — "No projects discovered" + scan-config
  explanation + CTA link to operator guide.
* `recall.no-matches` — "No matches found" + broaden-question hint
  + button "Clear filters" that resets question/project/host.
* `reembed.no-runs` — "No reembed runs yet" + run-now hint + button
  "Run now" that calls `triggerManual()`. Disabled when a run is
  already in flight.
* `trajectory.no-entries` — "No questions asked yet" + ask-form
  hint + button "Focus ask form" that focuses the Ask textarea.
* `fanout.no-selection` — "Pick at least one project" + select-all
  hint + button "Select all" that calls `selectAll()`.

The `x-show` conditions stay exactly as they were — purely
presentational change. Each block also binds `:aria-hidden` to the
inverse of its `x-show` so AT trees stay consistent.

### 3 · Static audit test (`tests/ui/test_empty_states.py`)

28 new test parametrisations (5 surfaces × 5 invariants + 3 free):

* `test_empty_state_has_headline` — canonical
  `font-bold text-gray-200` headline class present.
* `test_empty_state_has_body` — `text-xs text-gray-400` or
  `text-[11px] text-gray-400` body line present.
* `test_empty_state_has_cta` — either anchor link or
  `<button aria-label=>` button.
* `test_empty_state_carries_role_status` — `role="status"` for
  polite SR announcement.
* `test_empty_state_binds_aria_hidden` — symmetry with `x-show`.
* `test_empty_state_partial_exists` — partial file is present
  with the canonical slot tokens.

The `data-empty-state` attribute is the contract: future surfaces
add their entry to the `SURFACES` list and inherit all 5 audits
automatically.

## Real numbers

- 6/6 v8.0.0a3 sub-items shipped (full Phase 3 plan)
- 1 feature branch merged (no PR)
- +28 new tests (821 → 849 collected; +0 source files, 52 total)
- mypy --strict + ruff: clean
- Backwards-incompatible changes: 0
- Templates touched: 4 / 5 (dashboard, fan_out, project_detail; new
  `_partials/_empty_state.html`)

## What worked

- **Inline-rendered, partial-available.** The Alpine `x-show` on
  each surface needs a literal scope reference (e.g.
  `selected.length === 0`), so we kept the per-surface markup
  inline rather than forcing a Jinja-include wrapper. The partial
  exists for surfaces that don't need Alpine-conditional rendering
  — best-of-both.
- **`data-empty-state="<surface>"` as the audit contract.** Lets
  the test discover surfaces by attribute rather than by template
  scanning. Adding a new empty state means: add the markup, add
  the surface to `SURFACES`, done.
- **CTA per surface, not a generic dismiss.** Operators on
  "fanout.no-selection" see "Select all"; on "trajectory.no-entries"
  they see "Focus ask form". Each CTA points at the next obvious
  action — empty states stop being walls and become signposts.

## What we'd do differently

- **Snapshot test instead of substring assertion.** The current
  test asserts "headline class is present" — it would catch a
  drop-back to one-line `<p class="text-xs text-gray-500">no…`
  but not a subtle headline word change. v8.0.0a4+ could add a
  golden-file snapshot per surface (text-only, normalize whitespace)
  for a tighter contract. Deferred — the substring test is
  sufficient for the current churn.

## Action items for the next sprint (v8.0.0a4)

1 · Phase 4 — Cmd-K command palette. Global Alpine `commandPalette`
component mounted in `base.html`, `Cmd+K` / `Ctrl+K` trigger,
fuzzy-match across Projects + Tools + Settings/Help, keyboard nav
(↑↓/Enter/Esc), help-popover entry.

## Out-of-scope (still)

- Light-mode color swap of empty-state borders (user explicitly
  skipped light mode).
- Monochrome SVG illustration per surface — text-only is
  intentionally minimal and matches the dashboard's reductive
  palette.
- Animated "fade-in" transition on empty-state appearance — pure
  visual polish, costs less than 200 bytes of CSS but bumps the
  blast radius into Tailwind v4 territory (Phase 7).

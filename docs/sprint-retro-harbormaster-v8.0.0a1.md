# Sprint Retro — Harbormaster v8.0.0a1

**Date:** 2026-05-10
**Theme:** UI polish line opens — Phase 1 ships the accessibility
floor (the "if you can't see this surface with a screen reader,
nothing else in v8 matters" baseline). Pure additive a11y attribute
work across every interactive surface, plus a static audit test that
fails if the next template edit drops one of the invariants.

## What landed

### `harbormaster` (this repo)

| SHA | Subject |
|-----|---------|
| (merge) | feat(ui): a11y floor — aria-label, aria-live, aria-busy, focus-visible rings |

## Capabilities (this sprint)

### 1 · Accessible names on every icon-only button

Header help-popover toggle (`?` / `×`), in-popover close, reembed
trigger / cancel, fan-out select-all/none, fan-out copy-link, graph
reset-zoom, every `stop` button on streaming forms, every per-card
`ask` toggle, every trajectory expand toggle. Each carries a
descriptive `aria-label` (or a bound `:aria-label` for state-aware
labels like "Open inline ask form for {project}").

### 2 · Live-region semantics on streaming output

Every `<pre x-show="streamText">` now declares
`aria-live="polite" aria-atomic="false" aria-label="Streaming
answer"`. A screen reader announces incremental chunk arrivals
without re-reading the whole transcript on each update.

### 3 · Alert semantics on error displays

Every `x-show="error"` (and the sibling `bridgeError`,
`pluginsError`, `graphError`) container now declares
`role="alert" aria-live="assertive"`. Errors interrupt the SR queue
the moment they appear instead of waiting for the user to navigate
to them.

### 4 · `:aria-busy` binding on streaming submit buttons

Every Ask / Delegate / Fan-out / Search / Reembed-trigger /
Reembed-cancel button binds `:aria-busy="loading"` (or `triggering`
/ `cancelling`). Assistive tech announces the in-flight state
without polling visible text changes.

### 5 · `:aria-hidden` on `x-show`-toggled elements

Alpine's `x-show` only flips `display:none` — it doesn't add
`aria-hidden`. Browser AT trees often respect `aria-hidden` even
when CSS hides the node. Every interactive `x-show` block now binds
`:aria-hidden` to the inverse of the show condition for symmetry.

### 6 · `aria-controls` + `aria-expanded` on the help popover

The header `?` button declares `aria-controls="hm-help-popover"`
and `:aria-expanded`. The popover itself carries `id`, `role=dialog`,
and `aria-label="Keyboard shortcuts"`. SR users can navigate to the
popover and back via the standard "linked control" jump.

### 7 · Visible focus rings via `focus-visible:ring-*`

Every interactive element (button, link-button) now applies
`focus-visible:outline-none focus-visible:ring-2
focus-visible:ring-cyan-400 focus-visible:ring-offset-2
focus-visible:ring-offset-gray-950` (amber-400 ring on cancel
buttons to match the destructive intent). Keyboard nav is now
visually obvious; pointer-driven focus stays clean (the
`:focus-visible` selector skips the ring on click).

### 8 · Contrast bump from `text-gray-500` → `text-gray-400`

On the `bg-gray-950` body background, `text-gray-500` drops below
WCAG AA at small sizes (~3.6:1). Promoted to `text-gray-400` (~5.5:1
on the same background) on every interactive secondary-label
position the audit found: status-strip messages, share-link button
copy, "no projects match" prose, in-popover close link, ask-form
streaming/`hasResult` indicators.

### 9 · Static a11y audit test (`tests/ui/test_a11y_floor.py`)

17 new test parametrisations enforcing the invariants above:

* `test_template_well_formed_html` — every template parses via
  `html.parser` without exception (5 templates × 1 = 5 tests).
* `test_base_html_has_lang` — `<html lang="en">` present.
* `test_icon_only_buttons_have_accessible_names` — custom HTML
  parser walks every `<button>`, classifies icon-only by inner
  text + glyph table, asserts each carries `aria-label` /
  `:aria-label` / `aria-labelledby` (5 templates × 1 = 5 tests).
* `test_stream_panes_have_aria_live` — every `x-show="streamText"`
  pane declares `aria-live`.
* `test_error_displays_have_alert_role` — every `x-show="error"`
  (and analogous `…Error` aliases) declares `role="alert"`.
* `test_streaming_submit_buttons_bind_aria_busy` — every
  `<button type="submit">` whose `:disabled` references `loading`
  also binds `:aria-busy`.

The audit is intentionally strict: it fails on the next template
edit that drops one of these attributes, surfacing the regression
at PR-author time rather than after a screen-reader user files an
issue.

## Real numbers

- 9/9 v8.0.0a1 sub-items shipped (full Phase 1 plan)
- 1 feature branch merged (no PR)
- +17 new test parametrisations (797 → 814 collected; +0 source files,
  52 total)
- mypy --strict + ruff: clean
- Backwards-incompatible changes: 0
- Templates touched: 5 / 5 (every template now passes the audit)

## What worked

- **Static audit before runtime audit.** The HTML-parser-based
  template walk catches "is the attribute present" without booting
  a browser, axe-core, or Playwright. Faster CI, smaller blast
  radius, no flakes from headless-Chrome version skew.
- **Bind `:aria-hidden` symmetrically with `x-show`.** Three lines
  per element, every time. Once it's a habit it costs nothing; the
  audit catches the elements the habit misses.
- **`focus-visible:` not `focus:`.** Mouse users don't see rings
  (no visual noise on click); keyboard users do (genuine usability
  win). One class change, two-audience benefit.
- **Promote contrast on the elements operators actually look at.**
  Helper text and "no matches" prose are read more often than the
  bright headings — those are exactly the spots where `text-gray-500`
  hurts most.
- **Add a glyph table to the audit.** `?`, `×`, `…`, `▾`, `▸`, `✓`,
  `⚠`, `●`, `✗`, `⊘`, `⏸` covers the v8 phase-2 badge symbols too,
  so phase-2 SVG/glyph badges automatically inherit the same audit.

## What we'd do differently

- **Audit the existing templates before writing the audit code.**
  Wrote the assertion "every error display has role=alert" first,
  then discovered 4 unmodified error containers in dashboard.html
  (`bridgeError`, `pluginsError`, `graphError`, the project-grid
  loading error). The fail-then-fix cycle worked but a quick grep
  pass first would have caught all 4 in one edit instead of four.
- **Consider a contrast-checker plugin in CI.** The `text-gray-500`
  → `text-gray-400` substitution is correct for body context but not
  enforced anywhere. v8.0.0a7 (Tailwind v4 + OKLCH) is the natural
  place to introduce a token like `--color-muted-foreground` and
  guarantee minimum contrast at the design-system level.

## Action items for the next sprint (v8.0.0a2)

1 · Phase 2 — color + icon for state badges. Bridge state
(`connected` / `disconnected` / `no FleetQ`) gets ✓ / ⚠ / ⊘ glyphs.
Trajectory tier badges (`fresh` / `stale` / `stuck`) get ● / spinner
/ ⚠. Reembed phase badges (`idle` / `running` / `done` / `failed`)
get ⏸ / spinner / ✓ / ✗. Each badge gets `aria-label="<state-name>"`
matching the v8.0.0a1 audit invariant.

## Out-of-scope (still)

- Light mode (user explicitly skipped — dark stays canonical).
- axe-core or full WCAG audit (Phase 1 is the floor, not the
  ceiling; v9 candidate).
- Skip-to-main-content link (single-page dashboard doesn't need it
  yet; will revisit after v8.0.0a6 sidebar lands).

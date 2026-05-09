# Sprint Retro — Harbormaster v7.0.0a2

**Date:** 2026-05-09
**Theme:** Static guardrail. Move detection of the v6.0.0/v6.0.1/v6.0.2
graph-render bug class from runtime (Playwright, slow) to static
template scan (instant, runs on every test pass).

## What landed

### `harbormaster` (this repo)

| SHA | Subject |
|-----|---------|
| `9b797a9` | feat(test): static template safety audit for x-show + measure-dependent libs |

## Capabilities (this sprint)

### 1 · `tests/ui/test_template_safety.py` — html.parser walk + ALLOWLIST

Walks every `*.html` under `src/harbormaster/ui/templates/` via
`html.parser`, tracks the live element stack, and flags any
`x-show="..."` whose descendant subtree contains a measure-dependent
library element. Measure-dependent classes: `mermaid`, `chart`,
`sortable`, `virtual-list`, `virtual-scroll`.

Three tests:

  1. `test_no_unallowlisted_x_show_around_measure_dependent_libs` —
     the audit. Fails on any unallowlisted match.
  2. `test_allowlist_entries_are_actually_present` — prevents stale
     allowlist entries from accumulating after refactors.
  3. `test_scanner_finds_a_real_pattern_in_dashboard` — sanity that
     the html.parser walk actually detects the known wrapper.

The current single allowlist entry is the `!graphLoading` wrapper
in `dashboard.html` — the JS flips the flag BEFORE `mermaid.run()`,
documented inline in both the template and the allowlist comment.
The Playwright assertion from v7.0.0a1 is the runtime backstop.

## Real numbers

- 1/1 v7.0.0a2 phase action items shipped
- 1 feature branch merged (no PR)
- 3 new unit tests (740 → 743 collected; the new file runs in <100ms)
- mypy --strict + ruff: clean (50 source files unchanged)
- Backwards-incompatible changes: 0

## What worked

- **html.parser stack walk over regex windows.** First attempt used a
  2KB lookahead window after each `x-show=` match — that captured
  sibling elements as "descendants" and produced 3 false positives.
  Switching to a real DOM walk fixed it without complicating the
  test and gave a proper "element is descendant of x-show wrapper"
  semantic.
- **Sanity test for the scanner itself.** A test that asserts the
  scanner finds the known safe pattern means a future regression
  in the scanner (e.g. someone "simplifies" the parser) surfaces
  immediately instead of silently disabling the audit.

## What to change / next

- **Lenient end-tag pop tolerates Jinja {% if %} / {% for %}.** The
  scanner uses a "pop until matching tag" strategy because the
  templates contain Jinja control flow that html.parser doesn't
  understand. This is fine for our current templates but if a
  template ever has unbalanced `<div>` tags inside a Jinja block,
  the stack could drift. Acceptable trade-off for now; revisit if
  templates grow more complex.

## Action items for the next sprint (v7.0.0a3)

1. **Cancel-running-reembed button.** Top of the v6 retro candidates.
   Add `POST /api/history/reembed/cancel`, a cancel flag in the
   reembed state file, and a UI button on the reembed panel.

## Out-of-scope (still)

- Lint Alpine `x-data` scopes for unhandled-promise patterns —
  similar to this audit but for `async () =>` bodies that don't
  await. Useful but lower-priority than the measure-dependent
  audit; not worth shipping until we hit a bug from it.
- Full visual regression — pixel diffs would catch even more
  Mermaid render glitches but maintenance > value at our scale.

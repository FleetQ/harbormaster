# Sprint Retro — Harbormaster v19.0.0a4

**Date:** 2026-05-10
**Theme:** Phase 4 of the v19.0 workspace redesign — Linear-inspired
violet OKLCH accent palette + global compact-density pass. The
biggest visual change of the v19 sprint; closes the operator's
"I see no difference" frustration after a1–a3 only moved structure
without touching brand.

## What shipped

- **`tailwind.input.css` rebuilt around hue 290 (violet) + cool
  near-black surfaces.** The semantic token names (`--color-accent`,
  `--color-accent-strong`, `--color-accent-soft`,
  `--color-surface-1/2/3`, `--color-foreground`,
  `--color-foreground-muted`, `--color-foreground-subtle`,
  `--color-border`, `--color-border-strong`) are unchanged so every
  template that already used them re-paints automatically. Only the
  OKLCH values flipped.
  - Accent: `oklch(0.78 0.13 290)` (was `0.78 0.13 215` cyan).
  - Accent-strong: `oklch(0.62 0.22 290)` (kept high enough for
    WCAG AA contrast on `surface-1` / `surface-2` — the dark-mode
    contrast smoke test caught a 3.4:1 dip when accent-strong was
    initially set to `0.54 0.21 290`, so the value was bumped to the
    accent-500 stop).
  - Surfaces: `0.15` / `0.18` / `0.22` lightness (down from
    `0.20` / `0.26` / `0.32`) with chroma `0.005`–`0.010` at hue 280
    for a faint cool tint vs the prior pure-gray.
  - New `--color-surface-0` page-canvas token at `0.12` lightness for
    pages that want a darker-than-nav background.
  - New `--color-border-subtle` (`0.22` lightness) for low-contrast
    dividers; existing `--color-border` and `--color-border-strong`
    re-tinted to match the cool surface.
  - Light-mode mirror updated to use the violet hue at low
    lightness (`accent` `0.55 0.18 290`, `accent-strong`
    `0.46 0.21 290`) so a Theme: light operator still sees a
    Linear-style violet brand.
- **Sweep — every raw `cyan-NNN` Tailwind utility migrated to a
  semantic accent token.** v13.0.0a2 had only swept the high-shade
  cyan classes; v19.0.0a4 catches the focus-ring (`ring-cyan-400`),
  hover-state (`bg-cyan-900/NN`), border (`border-cyan-900/40`),
  and form-element (`accent-cyan-500`) variants too. New mapping:
  - `ring-cyan-400` → `ring-accent`
  - `bg-cyan-900/NN` → `bg-accent-soft/NN`
  - `border-cyan-900/40` → `border-accent-soft/40`
  - `accent-cyan-500` → `accent-accent`
  - `bg-gray-9{50,00,00}/NN` → `bg-surface-{1,2,3}/NN`
  - `border-gray-{700,800,900}/NN` → `border-border-strong/NN`
  - `ring-offset-gray-950` → `ring-offset-surface-1`
- **Compact density pass.** Global tighten across all 11 templates:
  - `gap-{3,4}` → `gap-2`, `p-{3,4}` → `p-{2,2.5}`,
    `px-4` → `px-3`, `py-{3,4}` → `py-{2,2.5}`,
    `mb-6` → `mb-4`, `mb-3` → `mb-2`, `mt-3` → `mt-2`,
    `rounded-lg` → `rounded-md`.
  - The migration is one-shot via `scripts/migrate_v19a4_violet_compact.py`
    so the next operator can re-derive what changed and replay if
    needed.
  - 359 substitutions across 11 files; sidebar items, KPI strip
    cells, cards, tabs, modals all visibly tighter.
- **Tests rebalanced.** Three pre-existing tests baked old token
  names / values into assertions; updated:
  - `test_state_badge_and_prefill` — `bg-cyan-900/50` →
    `bg-accent-soft/50`.
  - `test_v14_memory_tags_and_undo::test_project_detail_renders_tag_pills`
    — same mapping.
  - `test_ui::test_reembed_panel_phase_badge_classes` — same
    mapping.
  - `test_light_mode_toggle::test_input_css_defines_theme_*` —
    expectations updated to the new violet-tinted oklch values.
- **New regression suite — `tests/ui/test_v19_violet_compact.py`.**
  - Compiled `tailwind.css` must define `--color-accent` at
    `oklch(.78 .13 290)` (violet hue 290).
  - Sweep across every template forbids `cyan-NNN` raw utility
    classes (any prefix: `bg`, `text`, `border`, `ring`,
    `ring-offset`, `accent`).
  - Sweep forbids opacity-suffixed `bg-gray-9NN/NN` /
    `border-gray-9NN/NN` — caught one stale `border-gray-800/60`
    in `_sidebar.html` that the migration regex initially missed
    (script extended to cover border-gray opacity variants).
  - Density assertion: dashboard contains compact `p-2.5` paddings.
  - Sanity sweep: every project-defined `--color-{accent,surface,
    border,foreground}*` token must use hue 280 or 290 — catches
    a partial revert to cyan.

## Verification

- Tailwind CSS recompiled via the standard hatch build hook
  (`npx @tailwindcss/cli` against the symlinked node_modules).
  Compiled artifact contains `--color-accent:oklch(78% .13 290)`.
- Full `pytest` run: 1719 collected, 1641 passed, baseline-equal
  (zero NEW failures vs `main` HEAD baseline; the 54 pre-existing
  SSE / network / bridge teardown failures are unrelated).
- mypy --strict: no issues found in 57 source files.
- ruff: clean on the 2 net-new files
  (`scripts/migrate_v19a4_violet_compact.py`,
  `tests/ui/test_v19_violet_compact.py`).
- Visual verification on a separate UI on port 17799 (operator on
  17636 left untouched, PID confirmed unchanged):
  - Dashboard: violet "STEP N OF M" pill + violet stat numbers on
    a true near-black canvas. KPI strip cells visibly tighter.
  - Project detail: condensed sidebar + tabs row + card padding.
  - Network: violet active-tab indicator, compact filter bar.
  - Dispatcher: violet header pill, compact event list rows.

## What didn't ship

- The accent shade scale `--color-accent-50 … --color-accent-900`
  was added to `@theme` but **Tailwind v4's tree-shaking** drops
  any token whose utility class isn't referenced in a template.
  Templates currently only reference `accent` / `accent-strong` /
  `accent-soft`, so the 50…900 stops aren't emitted in the
  compiled CSS. Future phases that want to use, e.g.,
  `bg-accent-300` will get the token "for free" once a template
  references it.
- `--color-border-subtle` was added but no template references it
  yet (planned for v19.0.0a5+ when the inspector dividers get a
  lower-contrast pass).

## Lessons

1. **Re-bind, don't rebrand.** Keeping the semantic token NAMES
   intact while flipping their VALUES is the cheapest way to swap
   a brand color across a 10-template app. The 359 template
   substitutions in this phase were not for the brand color
   (those happened automatically) — they were for residual raw
   `cyan-NNN` and `gray-9NN/NN` utility classes that v13 had left
   behind.
2. **Contrast smoke tests catch design drift.**
   `test_dark_mode_pairs_meet_wcag_aa` flagged `accent-strong` at
   3.4:1 on the new dark surfaces before any visual review. Without
   it, the violet rebrand would have shipped a barely-visible
   primary CTA color. Worth keeping the WCAG smoke test green even
   for "purely visual" changes.
3. **Tailwind v4 tree-shakes unused @theme tokens.** Adding the
   accent-50…900 scale to `@theme` does NOT make
   `--color-accent-500` available in the compiled CSS unless a
   template uses (e.g.) `bg-accent-500`. The v19a4 spec drafted a
   test for `--color-accent-500` in the compiled CSS — replaced
   with a test for `--color-accent` (which IS used) plus a hue
   sanity sweep that proves every emitted accent/surface/border/
   foreground token is on hue 280 or 290.
4. **Migration script in `scripts/` over inline Edit calls.**
   Running ~360 substitutions one Edit call at a time would have
   been prohibitively slow and error-prone. A 80-line Python
   migration script run via Bash, dry-run first, then for-real, is
   the right tool for this scale of change. The script is committed
   for traceability of what changed in the rebrand.

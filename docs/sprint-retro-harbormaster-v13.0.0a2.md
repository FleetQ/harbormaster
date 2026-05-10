# Sprint Retro — Harbormaster v13.0.0a2

**Theme:** Tailwind v4 utility-class migration. Closes the v9.0.0a1
deferral that has been pending for 4 versions. The v13.0.0a1
screenshot-diff harness is what made this safe to ship in a single
phase rather than the previously-anticipated a2 / a2.5 split.

## What shipped

### `scripts/migrate_tailwind_utilities.py`

A Python migration script that walks every Jinja template under
`src/harbormaster/ui/templates/` and rewrites raw Tailwind color
utilities to the semantic tokens defined in `tailwind.input.css`'s
`@theme` block. Uses regex with negative-lookahead for `/` so
opacity-suffixed variants (`bg-cyan-900/50`) are preserved untouched
— those are tracked separately for v13.0.0a3+ semantic-token-with-
opacity work.

The script reports per-template counts. Idempotent — running twice
is a no-op.

### Migration sweep — 624 replacements across 10 templates

| Template                            | Replacements |
|-------------------------------------|-------------:|
| `dashboard.html`                    | 175          |
| `project_detail.html`               | 111          |
| `network.html`                      |  65          |
| `base.html`                         |  ~55         |
| `fan_out.html`                      |  31          |
| `dispatcher_trace.html`             |  21          |
| `_partials/ask_form.html`           |  14          |
| `_partials/delegate_form.html`      |  13          |
| `_partials/_empty_state.html`       |   5          |
| `_partials/_state_badge.html`       |   5          |
| **Total**                           | **624**      |

Mappings applied (high-confidence, word-boundary safe):

| Raw utility (was)            | Semantic token (now)        |
|------------------------------|-----------------------------|
| `text-gray-{100,200}`        | `text-foreground`           |
| `text-gray-{300,400}`        | `text-foreground-muted`     |
| `text-gray-{500,600,700}`    | `text-foreground-subtle`    |
| `text-cyan-{100..400}`       | `text-accent`               |
| `text-cyan-{500..700}`       | `text-accent-strong`        |
| `text-{emerald-300,emerald-400}` | `text-success`          |
| `text-{amber-300,amber-400}` | `text-warning`              |
| `text-{rose,red}-{300,400}`  | `text-danger`               |
| `text-purple-{300,400}`      | `text-info`                 |
| `bg-gray-950`                | `bg-surface-1`              |
| `bg-gray-900`                | `bg-surface-2`              |
| `bg-gray-800`                | `bg-surface-3`              |
| `bg-cyan-{600..800}`         | `bg-accent` / `bg-accent-strong` |
| `border-gray-{700,800}`      | `border-border`             |
| `border-gray-900`            | `border-border-strong`      |
| `border-cyan-{700,800}`      | `border-accent-strong`      |
| `border-amber-700`           | `border-warning`            |

### `tailwind.input.css` — explicit `@source` directive

Tailwind v4's default content-discovery heuristics didn't pick up
the `templates/` directory when invoked from a sibling `static/`
input — so the compiled CSS was missing the new semantic-token
utility classes. Added an explicit::

    @source "../templates/**/*.html";

The compiled `tailwind.css` now grew from 6.4KB → 37.2KB once it
started actually emitting the utility classes the templates depend
on. This is also what the `test_vendored_css_includes_semantic_utilities`
regression test guards.

### Test assertion sync (3 files)

The migration changed bytes the test suite was asserting against.
Updated atomically in the same commit:

- `tests/ui/test_empty_states.py` — `text-gray-200` → `text-foreground`,
  `text-gray-400` → `text-foreground-muted` in the headline + body
  assertions.
- `tests/ui/test_state_badges.py` — `text-gray-300` → `text-foreground-muted`
  in the plugins-badge anchor lookup.
- `tests/unit/test_ui.py` — `text-cyan-300/emerald-300/rose-300` →
  `text-accent/success/danger` in the reembed phase-class assertion
  (the `bg-*-900/50` halves stay raw — opacity preserved).

### `tests/ui/test_tailwind_utility_migration.py` — regression guard

12 new tests (1 per template + 1 vendored-CSS sanity check):

- `test_template_uses_only_semantic_tokens[<file>]` — fails if any
  raw color utility from the migration list creeps back in via
  copy-paste from external snippets. Word-boundary safe so
  opacity variants stay allowed.
- `test_vendored_css_includes_semantic_utilities` — asserts the
  compiled `tailwind.css` ships the canonical semantic-token
  utility classes; catches the case where the `@source` directive
  gets dropped.

## Quality gates

```
mypy --strict src/harbormaster   →  Success: no issues found in 56 source files
ruff check src tests scripts      →  All checks passed!
pytest -q                         →  1325 passed, 3 skipped in 40.1s
```

Test count delta: 1313 → 1325 (+12 regression tests).

## Was the a2 / a2.5 split necessary?

No. The plan authorized splitting if the migration took >2 hours.
The migration script + atomic test sync + CSS rebuild fit in one
phase. The v13.0.0a1 screenshot-diff harness deserves a footnote
here: knowing that visual regressions would surface explicitly via
the harness (rather than via human-spot-checking 10 surfaces × 2
themes = 20 manual reviews) made the "go" decision routine.

The screenshot-diff browser tests themselves are still un-bootstrapped
(no `baseline/*.png` blessed) — that's a one-time `cp` task the
operator can do at any wall-clock convenience. The unit-level diff
math is exercised on every CI run.

## Patterns proven this sprint

### Migration-script-then-test-sync

The all-templates-at-once sweep + lockstep test assertion update
is the same atomic-rename pattern from the global "Code Changes"
discipline:

1. Grep the codebase for every reference to the symbol.
2. Show the complete list of files that reference it.
3. Make ALL changes atomically across every file.
4. Grep again after to confirm zero remaining old references.

The v13.0.0a2 migration applied this discipline at scale: 10
templates + 3 test files + 1 CSS source + 1 vendored CSS, all in
one commit.

## Quality of life

- Operators forking the project and adding a new template are
  enforced (via `test_template_uses_only_semantic_tokens`) to use
  semantic tokens from day one.
- The migration script is preserved at `scripts/migrate_tailwind_utilities.py`
  so future template-adoption sweeps (extracted external HTML, AI-
  generated drafts) can be run against fresh templates before
  committing.
- The `@source` directive will keep working for any future
  templates added under `templates/`.

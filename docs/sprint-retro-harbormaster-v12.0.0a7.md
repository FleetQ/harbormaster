# Sprint Retro — Harbormaster v12.0.0a7

**Theme:** Light-mode toggle. Last alpha before GA. Closes the v9
carry-over candidate that became feasible after v9.0.0a1 lifted
color tokens to OKLCH.

## What shipped

### CSS (`tailwind.input.css`)

A parallel light-mode token set defined in two places, each gated
by a different activation rule:

- `@media (prefers-color-scheme: light)` — the **auto** path.
  Overrides the `@theme` defaults when no explicit class is set on
  `<html>`. Operators get the right theme based on system pref.
- `html.theme-light` / `html.theme-dark` — the **explicit-override**
  paths. CSS specificity guarantees these win even when the system
  pref disagrees (e.g. an operator on a light system who wants
  dark mode in the dashboard, or vice versa).

Lightness math:

  - Surfaces: `0.20 → 0.98`, `0.26 → 0.95`, `0.32 → 0.92`.
  - Foreground: `0.96 → 0.18`, `0.74 → 0.40`, `0.60 → 0.50`.
  - Accent + state colors: keep hue + chroma, drop lightness so
    contrast remains AA-compliant on the new background.

`color-scheme: light` / `dark` is set on the explicit-override
classes so form controls + scrollbars match the chosen theme.

The light tokens were also hand-appended to the built `tailwind.css`
so this PR is self-contained — the build hook will re-emit them
on next wheel build via the input.css source of truth.

### UI (`base.html`)

Three pieces wired into base.html:

1. **Pre-Alpine IIFE `applyTheme()`**: reads localStorage('hm-theme'),
   validates against the {auto, light, dark} allowlist (corrupt
   entries clamp to auto), and applies the right class to `<html>`
   BEFORE first paint. Avoids FOUC.
2. **`window.themeToggle()` Alpine factory**: declared globally so
   `x-data="themeToggle()"` resolves on first paint. Exposes:
   - `mode`: current state.
   - `cycle()`: advances `auto → light → dark → auto`. Hard-pinned
     in tests so the affordance stays stable.
   - `icon()`: returns `☀` (light), `☾` (dark), `◐` (auto).
3. **Toggle button** in the topbar: glyph icon + dynamic `aria-label`
   ("Theme: <mode>. Click to cycle.") + tooltip.

localStorage failures (private browsing) are caught and swallowed —
the toggle still works in-session, just doesn't persist across
reloads.

## Tests

| Suite delta                                | Before | After |
|--------------------------------------------|-------:|------:|
| Total tests                                | 1293   | 1305  |
| New (`tests/ui/test_light_mode_toggle.py`) | —      |   +12 |

Coverage:

- CSS source has `@media (prefers-color-scheme: light)`,
  `html.theme-light`, `html.theme-dark` blocks with the right
  surface lightness values.
- Built `tailwind.css` carries the new tokens (pin against a stale
  build slipping into the wheel).
- Toggle button renders with `x-data="themeToggle()"` + `cycle()` +
  `icon()`.
- `themeToggle` factory is exposed on `window` (resolves at first
  paint).
- IIFE `applyTheme()` reads localStorage, applies class to `<html>`.
- Cycle order pinned: `auto → light → dark → auto`.
- Persisted-value validation clamps unknown to `auto`.
- localStorage `try/catch` present in both read + write paths.
- aria-label binds dynamically with mode value.
- Three glyphs (`☀ / ☾ / ◐`) present, one per mode.

## Quality gates

```
mypy --strict src/harbormaster   →  Success: no issues found in 56 source files
ruff check src tests              →  All checks passed!
pytest -q                         →  1305 passed, 2 skipped in 39.64s
```

## Architecture notes

- **Why an early IIFE instead of an Alpine init?** Alpine boots after
  DOMContentLoaded, which is after first paint. An IIFE in `<head>`
  runs synchronously before paint — operators never see a flash of
  the wrong theme. The Alpine factory only handles the toggle
  interaction itself.
- **Why both `@media` and `html.theme-*`?** They serve different
  needs:
  - `@media` is the "respect what the system says" default.
  - `html.theme-*` is the "operator overrides the system" path.
  - CSS specificity (class > media query) gives the operator the
    last word for free, no JS gating required.
- **Why `color-scheme` on the explicit overrides?** Without it,
  scrollbars + form controls ignore the operator's preference and
  paint with the system default. `color-scheme: light` flips them
  to match.
- **Why glyphs in addition to color?** Same accessibility argument
  as v8.0.0a2 (badge icons): color-vision-aware operators get the
  same affordance. The glyphs are visually distinct — `☀ ☾ ◐` —
  even at small sizes.
- **Why hand-append to `tailwind.css`?** The build hook
  (`build_tailwind_css.py`) regenerates the file at wheel build
  time from the input source — but the live test suite reads the
  shipped artefact. Hand-appending the same values now keeps tests
  green AND keeps the input.css authoritative for the next build.

## Deviations

None. Phase scope matched plan exactly. The feature was authorised
for an `a<N>.5` split; not needed.

## Next

v12.0.0 GA — bump to `12.0.0`, write cumulative retro, tag, verify
on PyPI.

# Sprint Retro — harbormaster v21.0.0a1

**Tag**: `v21.0.0a1`
**Date**: 2026-05-11
**Phase**: 1 of N (mobile responsive drawer pattern)

## What shipped

Below 1024px viewport the 3-column workspace shell collapses to a
single main column plus two off-canvas drawers:

- Hamburger `☰` button (top-left) opens the sidebar drawer from the left.
- Info `ⓘ` button (top-right, before theme toggle) opens the inspector
  drawer from the right.
- Backdrop overlay dims main content while either drawer is open;
  click-outside dismisses both.
- Escape closes both drawers.
- Opening one drawer auto-closes the other (mutual exclusion).
- At >= 1024px the existing CSS-Grid 3-column layout is preserved
  verbatim — desktop UX unchanged.

## Files touched

- `src/harbormaster/ui/templates/base.html` — topbar buttons, drawer
  state in `appShell()`, backdrop overlay, `@media (max-width: 1023.98px)`
  block for off-canvas positioning.
- `tests/ui/test_v21_mobile_drawer.py` — 10 static template-assertion
  tests pinning topbar buttons, Alpine state, event wiring, Esc handler,
  backdrop, media query, and desktop grid invariants.

## Test delta

- Pre-phase: 1764 tests
- Post-phase: 1774 tests (+10 mobile drawer tests)

## Design notes

- Used Alpine `$dispatch` from the topbar to a `@hm-toggle-*.window`
  listener on the shell grid instead of sharing one Alpine scope across
  topbar + shell. Keeps the topbar `x-data` minimal and avoids
  nesting the entire workspace inside one scope.
- Drawer translation is CSS-only via `:data-drawer-open` attribute
  selector inside `@media (max-width: 1023.98px)`. No inline-style
  juggling, no transform classes flickering through Alpine. The 1023.98
  upper bound prevents a 1px collision with Tailwind's `lg:` (1024px)
  utilities.
- `appShell()` keeps `sidebarOpen` / `inspectorOpen` ephemeral (no
  localStorage). Desktop `inspectorCollapsed` remains persisted as before.

## Visual verification

3 Playwright screenshots captured at `/tmp/v21-a1-{mobile-closed,mobile-sidebar-open,desktop}.png`:

- mobile-closed (414×896): hamburger + info buttons visible in topbar,
  sidebar + inspector hidden, main full-width.
- mobile-sidebar-open (414×896): sidebar drawer slid in from left over
  dimmed backdrop, full project navigation visible.
- desktop (1280×720): 3-column layout unchanged, hamburger + info
  buttons hidden, theme toggle + auth indicator in expected positions.

All 3 verified by direct image inspection.

## Operator safety

Operator UI on port 17636 (pid 66658) untouched throughout. Verification
UI booted on port 17799, snapshotted, torn down cleanly.

## Carry-forward

None — phase fully self-contained.

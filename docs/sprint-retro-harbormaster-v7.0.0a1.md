# Sprint Retro — Harbormaster v7.0.0a1

**Date:** 2026-05-09
**Theme:** Regression-detection. Add the assertion that would have caught
the v6.0.0/v6.0.1/v6.0.2 graph-render bug class on the first commit
instead of letting it live for 17 versions.

## What landed

### `harbormaster` (this repo)

| SHA | Subject |
|-----|---------|
| `f86bcb2` | feat(test): browser SVG-render assertion guards graph render regressions |

## Capabilities (this sprint)

### 1 · Browser SVG-render assertion (`tests/ui/test_browser_smoke.py`)

The Playwright suite now reads the actual `<svg>` bbox after Mermaid
runs and asserts `width > 50 && height > 10`. A placeholder /
unrendered SVG sits at Mermaid's transparent ~16×16 stub; a real
rendered diagram is well over 50px even for the seeded one-node
graph. This closes the v4.0.0a3 → v6.0.2 detection gap that hid
three different graph-render bugs:

  - v6.0.0: graph not loading at all
  - v6.0.1: x-show + measure race condition
  - v6.0.2: viewBox stuck at 16×16 placeholder

The previous browser smoke only asserted the `<pre.mermaid>` element
was present, not that Mermaid had rendered into it. The new
assertion runs in CI alongside the existing `smoke-ui-browser` job.

## Real numbers

- 1/1 v7.0.0a1 phase action items shipped
- 1 feature branch merged (no PR; per skip-PR-default convention)
- 1 new Playwright test (740 → 741 collected)
- mypy --strict + ruff: clean (50 source files unchanged)
- Backwards-incompatible changes: 0

## What worked

- **Single-purpose alpha tag.** Phase 1 was deliberately one assertion,
  not a refactor of the smoke suite. Easier to reason about, easier
  to revert if Playwright behaves unexpectedly in CI.
- **Reusing `pre.mermaid` as the wait selector.** The existing v6.0.2
  fix landed `class="mermaid"` on the `<pre>`, so the new assertion
  attaches to a stable selector that the patch class already touched.

## What to change / next

- **Test assertion threshold.** Picked `width > 50` arbitrarily — the
  seeded one-node graph in browser smoke is small; if upstream
  Mermaid changes node padding, this could go flaky. If that
  happens, drop the threshold and assert `width !== 16` instead
  (placeholder is exactly 16, any real render is non-16).

## Action items for the next sprint (v7.0.0a2)

1. **Audit `x-show + measure` template patterns.** Add a static check
   (Python unit test, not Playwright) that greps the templates for
   `x-show.*loading` wrapping `mermaid|chart|sortable|virtual`
   measure-dependent libs. Catch the bug class at template-edit
   time, not runtime.

## Out-of-scope (still)

- Full visual regression testing — pixel diffs would catch even
  more, but the maintenance burden outweighs the value at our
  current dashboard surface area.

# Sprint Retro — Harbormaster v16.0.0a4

**Date:** 2026-05-10
**Theme:** Diff/comparison viz polish — side-by-side HTML for the
cross-host config diff endpoint plus a tiny SVG sparkline helper for
the upcoming N-way reembed comparison panel.

## What shipped

- **`GET /api/config/diff?format=html`** (carry-over #10). Returns
  a complete `difflib.HtmlDiff().make_file()` document with `tabsize=4`,
  `wrapcolumn=80`, and 3 lines of context. The response is
  `text/html` so the operator can drop the URL into an iframe / new
  tab without further wrapping. `?format=json` (the v15.a2 default)
  is byte-identical for back-compat. Invalid `?format=` returns 400.
- **`_partials/_tiny_sparkline.html`** (carry-over #11). Roll-our-own
  SVG sparkline at ~50 LOC, no new CDN dep. Defines a
  `window.sparklineHtml(values, opts)` global that returns an HTML
  string suitable for `x-html=` binding on a per-cell `<span>`.
  Behaviour pins:
  - Empty / non-array input returns `''`.
  - Single value or zero-range values render flat at mid-height.
  - NaN / null / undefined coerced to 0.
  - `aria-label` lists the value sequence so screen-reader users
    perceive the trend.
- **`base.html`** now includes both v16 partials
  (`_cached_getter.html` + `_tiny_sparkline.html`) so every page has
  the helpers loaded.

## Numbers

- **Tests**: 1553 → 1568 (+15 net new — 5 endpoint tests + 6
  partial tests + 4 helper-shape pins)
- **Source files**: 57 (unchanged — extensions only)
- **Wall-clock**: ~25 min
- **Commits on main**: 1 feature merge
- **Lint / type**: ruff clean, `mypy --strict` clean
- **Backwards-incompatible changes**: 0
  - `/api/config/diff` default `format=json` returns the same shape.
  - The sparkline partial is brand-new; no prior contract.
  - `routes.py` imports gained `JSONResponse` (additive).
- **Confirmation: did NOT touch `.github/workflows/*`** — yes.

## What worked

- **`difflib.HtmlDiff` is stdlib gold.** Zero new deps, the output
  is self-contained CSS + table markup, and the side-by-side view
  matches the v13.a3 memory-revisions toggle behaviour the operator
  already knows.
- **Vendored sparkline beats CDN.** The whole helper fits in a
  single 50-line `<script>` block and reuses Tailwind colour vars
  via `currentColor`. No supply-chain dependency, no version pin to
  manage, and `mypy --strict` doesn't see it (it's a template).
- **CWD discipline held.** All Bash calls in this phase ran from
  the worktree CWD without explicit `cd`. Discipline lapses for
  v16.a4: **0**.

## What to change for the next phase

- v16.a5 closes the budget triad — per-project budget joins the
  per-host (v14.a4) and per-tool (v15.a4) caps. Keep the
  tightest-cap-wins logic as a tiny pure helper so the three caps
  stay symmetric.

## Notes for v16.a6 split decision

Backend instrumentation (the risky part) hasn't started yet.
Decision deferred to a6 itself.

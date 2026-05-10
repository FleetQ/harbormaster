# Sprint Retro — Harbormaster v13.0.0a5

**Theme:** Three small smoke tests bundled together. Closes three
v12-retro loose ends in one phase.

## What shipped

### `tests/ui/test_smoke_bundle_v13.py` — 7 new tests

#### 1. CSS `@theme` reload smoke (v12 retro #1)

Two complementary checks:

- `test_theme_toggle_swaps_html_class` — pins the
  `themeToggle()` Alpine helper's contract: the html class swap
  uses `classList.remove('theme-light', 'theme-dark')` THEN
  `classList.add(...)`. Asserted at the boot-script + cycle paths
  (verifies the remove-before-add appears at least twice).
- `test_css_variables_have_light_and_dark_overrides` — asserts
  the compiled `tailwind.css` carries explicit `html.theme-light`
  and `html.theme-dark` selector blocks AND that each block
  overrides the canonical `--color-surface-1` and
  `--color-foreground` tokens. Without these the html class moves
  but the computed CSS variable doesn't — the original v12 retro
  bug pattern.

#### 2. Cookie-behind-nginx smoke (v12 retro #2)

Two scenario tests using `TestClient` with proxy-style headers:

- `test_set_cookie_survives_proxy_headers` — request arrives with
  `X-Forwarded-{Proto,Host,For}` + a `Host:` rewritten to the
  external hostname; the auth cookie endpoint must still emit a
  `Set-Cookie: hm-auth=…; HttpOnly` response (HttpOnly is the
  most important attribute behind a proxy — blocks JS access
  even if the proxy mis-forwards).
- `test_cookie_header_passes_through_proxy_request` — full round
  trip: set cookie via auth endpoint, then make a GET on
  `/api/health` with proxy headers + cookie but no bearer; must
  return 200 (the v12.0.0a6 cookie-fallback path).

This is intentionally a unit-level smoke test rather than an
integration test that actually spins up nginx in a container —
the test's value is pinning the request-shape contract that
nginx produces, not validating nginx itself.

#### 3. Light-mode contrast audit (v12 retro #7)

Three tests:

- `test_light_mode_pairs_meet_wcag_aa` — for every documented
  foreground/background pair (6 pairs covering body text,
  secondary text, primary CTA on canvas + elevated surfaces),
  computes the WCAG 2.1 contrast ratio directly from the OKLCH
  values in `tailwind.input.css` and asserts ≥ 4.5:1 (AA).
- `test_dark_mode_pairs_meet_wcag_aa` — same audit on the dark
  block. Skips pairs that the dark block doesn't override (the
  `@theme` defaults are themselves the dark values).
- `test_oklch_helper_known_pair` — sanity-check the OKLab →
  linear-sRGB conversion: pure black on pure white must compute
  to ~21:1, WCAG's documented maximum ratio.

Conversion math is implemented in pure Python via the OKLab
matrices documented at https://bottosson.github.io/posts/oklab/.
No browser, no `axe-core` vendoring — the audit runs in the
regular pytest pass and finishes in milliseconds.

## Quality gates

```
mypy --strict src/harbormaster   →  Success: no issues found in 56 source files
ruff check src tests scripts      →  All checks passed!
pytest -q                         →  1353 passed, 3 skipped in 39.8s
```

Test count delta: 1346 → 1353 (+7).

## Patterns proven this sprint

### "Smoke tests for the things that should never silently break"

All three tests share the same shape: pin a contract that's
too easy to break by accident in a future refactor. None of them
test the happy path (other tests do that); they specifically
guard against the failure mode the v12 retro flagged.

### Pure-Python contrast audit

The contrast audit avoids the standard `axe-core` + headless-Chrome
ceremony by computing WCAG ratios directly from the OKLCH values
in the source CSS. This is faster, has no browser dependency, and
reads the canonical token values rather than the rendered approximation.
Future palette tweaks (light or dark) get instant feedback in
the regular pytest pass.

## Quality of life

- Operators editing `tailwind.input.css` get immediate test
  feedback if a palette change drops below AA.
- Cookie+nginx interaction is now test-pinned without requiring
  Docker / a real nginx daemon for CI.
- The theme-toggle contract is locked — a future refactor that
  flips the class names or drops the remove-before-add would
  fail the unit test before reaching CI.

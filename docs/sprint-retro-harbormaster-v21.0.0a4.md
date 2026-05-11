# Sprint Retro — harbormaster v21.0.0a4

**Theme**: Bleach allowlist regression suite + light-mode WCAG AA
contrast verification. The memories editor's live-preview endpoint is
now pinned against the canonical XSS payload set, and every
`html.theme-light` OKLCH token clears the AA contrast floor against
every surface it can land on.

## What shipped

- **XSS regression suite** (`tests/ui/test_v21_xss_regression.py`, 9
  tests) — pins `render_safe()` against the canonical payload set so
  a future widening of the bleach allowlist (e.g. v15.0.0a6's
  `[markdown] strict = false` flag) can't silently let injection
  through. Covers:
  - `<script>` tag stripped.
  - `<iframe>` stripped.
  - `javascript:` / `data:` / `vbscript:` `href` schemes refused.
  - `onerror` / `onload` event-handler attributes stripped.
  - Positive controls: `https:` `<a>` preserved, v12.0.0a4
    `<details>`/`<summary>` allowlist extension preserved.

- **Light-mode contrast audit** — parsed every `html.theme-light`
  OKLCH token from `tailwind.input.css`, ran each through the OKLab
  → linear-sRGB → relative-luminance pipeline, and asserted WCAG AA
  ratios (4.5:1 text, 3:1 state-conveying UI). 31 parametrised pairs
  + a media-query/explicit-class parity check
  (`tests/ui/test_v21_light_mode_contrast.py`).

- **Three light-mode token gaps fixed**:
  - `foreground-subtle` L `0.55` → `0.48` — was 3.60–4.45 against
    surface-1/2/3; now 4.85–5.86.
  - `accent` L `0.55` → `0.50` — was 3.87 against surface-3; now
    4.80 (5.78 on surface-0).
  - `border-strong` L `0.72` → `0.58` — was 1.84–2.41 on every
    surface (state-conveying UI floor 3:1 missed everywhere); now
    3.18–4.17.

  Hue (290°) and chroma unchanged so the on-brand violet stays
  recognisable; only luminance moves so contrast crosses the AA
  floor. `border` / `border-subtle` are decorative (don't convey
  state) and kept their original values — only required to stay
  visible (>1.05 ratio against surface-1).

- **`tailwind.css` rebuilt** from the tuned input via the existing
  `npx @tailwindcss/cli` pipeline (the same path the wheel build hook
  uses). The committed artefact ships the tuned values for users who
  don't have Node installed.

- **Visual verification** — three Playwright screenshots
  (`/tmp/v21-a4-light-{dashboard,project,network}.png`) confirm that
  light mode renders cleanly: dark foreground text on near-white
  surfaces, visible card borders, violet accent still recognisable
  at the new darker shade.

## Stats

- **Tests**: +40 (9 XSS + 31 contrast), all green in isolation. New
  files only — no edits to existing test files.
- **Files modified**: 2 (CSS source + built artefact). 2 created
  (test files). No template / route / Python source changes — the
  bleach pipeline was already correct; this sprint pinned it.
- **Operator UI (port 17636)**: untouched throughout the sprint.
  Visual verification ran on a parallel UI bound to port 17799.

## What's next

Phase 5 of the v21.0.0 sequential release stream — orchestrator picks
the spec.

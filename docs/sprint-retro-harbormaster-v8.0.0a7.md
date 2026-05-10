# Sprint Retro — Harbormaster v8.0.0a7

**Date:** 2026-05-10
**Theme:** Phase 7 of the v8 UI polish line — distribution slim-
down. HTMX dropped (zero `hx-*` attributes ever in production
templates), semantic OKLCH color tokens added under `:root` in
`base.html`. Full Tailwind v4 vendor + utility migration deferred
to v9 with explicit rationale.

## What landed

### `harbormaster` (this repo)

| SHA | Subject |
|-----|---------|
| (merge) | feat(ui): drop HTMX, add semantic OKLCH color tokens |

## Capabilities (this sprint)

### 1 · HTMX script tag removed from `base.html`

Phase 1's audit (`tests/ui/test_a11y_floor.py`) plus a fresh
manual `grep -rn 'hx-'` confirmed zero HTMX attributes anywhere
in the templates. The CDN script tag was loading ~14KB of JS that
nothing referenced. Dropping it shaves the largest single
download from the cold-load budget without removing any
functionality. The dashboard fully migrated to Alpine + SSE in
v3.0; HTMX never came back.

### 2 · Semantic OKLCH token block under `:root`

16 new CSS custom properties under the canonical `--hm-*` prefix:

```css
:root {
  --hm-surface-1, --hm-surface-2, --hm-surface-3
  --hm-foreground, --hm-foreground-muted, --hm-foreground-subtle
  --hm-accent, --hm-accent-strong, --hm-accent-soft
  --hm-success, --hm-warning, --hm-danger, --hm-info
  --hm-border, --hm-border-strong
  --hm-ring
}
```

All values declared in `oklch()` for forward-compatibility with
the eventual Tailwind v4 `@theme` migration — when v9 lifts these
into the `@theme` block, the values transfer literally without
needing re-derivation from RGB hex.

The tokens are namespaced (`--hm-*`) so they cannot collide with
anything Tailwind CDN or third-party CSS injects. Component
authors should reference them via `var(--hm-accent)` etc.

### 3 · `[x-cloak]` rule centralized

`[x-cloak] { display: none !important; }` lifted into the same
`<style>` block. Previously every template that used `x-cloak`
relied on the implicit Alpine plugin behavior or copied the rule
inline. Now centralized; one source of truth.

### 4 · Static distribution audit (`tests/ui/test_phase7_distribution.py`)

27 new test parametrisations:

* `test_no_htmx_attributes[*5 templates]` — zero `hx-*` regression
  guard.
* `test_htmx_script_tag_removed_from_base` — script tag absent.
* `test_semantic_token_defined[*16 tokens]` — every canonical
  token present.
* `test_semantic_tokens_use_oklch` — every token declared with
  `oklch()` (no rgb/hex backsliding).
* `test_x_cloak_rule_centralized` — rule present.

Plus updated `tests/unit/test_ui.py::test_root_returns_dashboard_html`
to assert `htmx not in body` (was `htmx in body` before; flipped
+ documented).

## Real numbers

- 4/4 v8.0.0a7 sub-items shipped (Phase 7 plan, scoped down)
- 1 feature branch merged (no PR)
- +27 new tests + 1 flipped existing assertion (893 → 920
  collected; +0 source files, 52 total)
- mypy --strict + ruff: clean
- Backwards-incompatible changes: 0 user-facing (HTMX was unused
  internally — no consumer code referenced it)
- Page weight: -14KB on cold load
- Templates touched: 1 / 6 (base.html)

## What worked

- **Audit-first, removal-second.** Phase 1's HTMX audit gave us
  the empirical evidence to drop the script tag without
  speculation. "If it's not used, dropping it can't break
  anything" is only a safe argument when you've actually counted.
- **OKLCH tokens now, theme migration later.** Defining the
  tokens in OKLCH unblocks the v9 `@theme` migration without
  forcing the build-pipeline decision now. The tokens are usable
  via `var(--hm-*)` in any inline style or Tailwind CDN
  arbitrary-value class (`bg-[var(--hm-accent)]`) starting v8.0a7.
- **Namespaced custom properties.** `--hm-*` prefix isolates our
  tokens from anything Tailwind CDN or future libraries might
  inject. No collision risk; future-Tailwind-v4 migration just
  copies the block.
- **Single test asserting HTMX absence.** Guards against the
  classic "let's add HTMX back for this one feature" regression.
  The next person to type `<script src=...htmx...>` fails the
  audit at PR-author time.

## What we'd do differently — and the v8.0.0a7 SCOPE SPLIT

The original Phase 7 plan called for three things in one alpha:

  (a) Drop HTMX                                 ← shipped
  (b) Semantic OKLCH tokens                     ← shipped
  (c) Vendor Tailwind v4 + migrate every utility class to
      semantic-token classes                   ← DEFERRED to v9

**Rationale for the split:** (c) is a multi-decision change that
needs operator input we don't have authorisation to make
unilaterally:

* **Distribution path.** Two genuine options — vendor the
  `@tailwindcss/cli` standalone binary into `vendor/` (operators
  pay no Node toolchain cost but `uvx harbormaster-mcp` ships a
  ~10MB binary), OR build CSS at packaging time via a
  `pyproject.toml` build step (smaller wheel but operators with
  air-gapped installs get a slower install). The trade-off
  matters and warrants explicit user input.
* **Per-template migration.** ~150 utility classes across 5
  templates need to be rewritten to semantic-token classes. Each
  rewrite needs visual confirmation (Phase 1 audit doesn't catch
  visual regression). Without a Playwright screenshot-diff
  harness, we'd be flying blind on color-correctness.
* **CDN swap window.** Switching from Tailwind CDN to vendored
  Tailwind v4 means the dashboard is offline-capable but the CDN
  swap requires the new CSS file to ship in the same release the
  CDN script is removed. One bad merge = blank page.

The v8 phase plan explicitly authorised splitting Phase 7 with a
note in the retro: *"User authorized 'all in one alpha' but if it
genuinely won't fit, split with explicit note in retro."* We're
exercising that escape hatch deliberately.

The deferred work moves to **v9 candidate #1** (top of the v9
list, ahead of the trace waterfall) so it ships first in v9.
v8.0 GA documents this explicitly.

## Action items for v8.0.0 GA

1 · Bump to `8.0.0`, write the cumulative retro covering the 7
alphas + final test counts + the v9 candidate list.

## Out-of-scope (still — and v9 candidate)

- **Tailwind v4 vendor + utility migration.** v9 candidate #1.
- **Playwright screenshot-diff harness.** Needed before (1) can
  ship safely. v9 candidate.
- **Light-mode token branch.** User explicitly skipped light mode
  for v8; the OKLCH token block has the structure to add a
  `[data-theme="light"] :root { … }` overlay if v9 needs it.

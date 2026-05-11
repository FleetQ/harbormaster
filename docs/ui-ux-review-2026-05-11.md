# Harbormaster — UI/UX Review (post-v21.0.3)

**Date:** 2026-05-11
**Subject:** Live v21.0.3 source tree
**Stack:** FastAPI + Jinja2 + Alpine.js 3.x + Tailwind CSS v4 (CSS-based `@theme`) + Mermaid/Cytoscape
**Templates:** 15 files (~8 600 lines), 8 partials
**Reviewer:** Claude Opus 4.7 via `/ui-ux-review`

---

## TL;DR

Harbormaster's UI is **considerably more mature than a typical OSS dashboard** — the v19+v21 chain invested heavily in design tokens, light/dark mode, focus management, ARIA, and keyboard navigation. The audit found **zero critical issues** and only a small surface of medium/low-priority polish items.

**Status: GOOD** — ship-worthy as-is; the items below would push it from "good" to "excellent."

---

## Design system (✅ strong)

`src/harbormaster/ui/static/tailwind.input.css` defines an extensive
**Linear-inspired violet OKLCH palette** with:

- **3 theme paths**: `@theme` defaults (dark), `@media (prefers-color-scheme: light)`,
  and explicit `html.theme-light` / `html.theme-dark` classes.
- **Semantic tokens** for every conceptual role: `accent` (50–900),
  `surface-0…3`, `foreground` / `foreground-muted` / `foreground-subtle` /
  `foreground-dim`, `border-subtle` / `border` / `border-strong`,
  `success` / `warning` / `danger` / `info`, `ring`.
- **WCAG AA-tuned** light-mode values (v21.0.0a4 audit darkened
  3 tokens that failed text-contrast checks against surface-2/3).
- **Legacy `--hm-*` aliases** preserved so v8 distributions don't break.
- **`@source "../templates/**/*.html"`** for Tailwind v4 template
  scanning when input CSS lives in `static/`.
- **Operator-tunable accent** via a runtime `<style id="hm-custom-accent">`
  block mutated from `localStorage` (v21.0.0a3 — well-architected).

No raw hex colors, no random Tailwind shade jumps in templates. The 30
most-used class fingerprints are all built from semantic tokens.

---

## Strong patterns to preserve

These are all working well — list them so the next refactor doesn't
accidentally regress them.

1. **Focus-visible coverage on every template** — dashboard.html has 28,
   project_detail 23, network 8, base.html 7, partials 2–6 each. Keyboard
   users get a visible ring on every interactive element.
2. **`@click` only on `<button>`** — across 79 `@click` handlers there
   is **zero use** of `@click` on `<div>`/`<span>`/`<a>`/`<li>`/`<p>`.
   No keyboard-activation parity gaps; native `<button>` semantics apply.
3. **136 `aria-label` attrs + 73 `role` attrs** — `role="alert"` (28×),
   `role="status"` (16×), `role="tabpanel"` (13×), `role="dialog"` (5×
   with `aria-modal`), `role="tablist"`/`tab` in `_tabs.html`.
   Solid screen-reader scaffolding.
4. **Semantic landmarks**: one canonical `<main id="hm-main">` in
   `base.html` wraps every page's content block. `<nav>`, `<aside>`,
   `<header>`, `<section>`, `<article>` used appropriately throughout.
5. **`role="dialog"` + `aria-modal` + `aria-labelledby`** on all 5
   modal/popover surfaces (Cmd-K palette, keyboard cheatsheet,
   memory editor, etc.).
6. **`_empty_state.html` partial** exists, with `focus-visible` already
   wired (though under-used — see Medium-2 below).
7. **`@source` directive** in tailwind.input.css forces Tailwind to scan
   Jinja templates — closes the v13.0.0a2 stack-mismatch gap that
   would have caused utilities to be tree-shaken out.

---

## Findings

### 🟡 MEDIUM-1 — no `<h1>` on any page

Zero `<h1>` elements exist across the 15 templates. The site brand
"Harbormaster" lives in an `<a>` inside `base.html`'s header bar
(line 198), and the per-page title sits in a `<span>` via the
`{% block page_title %}` slot (line 203).

| Template | h1 | h2 | h3 | h4 |
|---|---:|---:|---:|---:|
| `dashboard.html` | **0** | 4 | 13 | 1 |
| `project_detail.html` | **0** | 1 | 9 | 0 |
| `network.html` | **0** | 1 | 5 | 0 |
| `fan_out.html` | **0** | 1 | 2 | 0 |
| `dispatcher_trace.html` | **0** | 1 | 5 | 0 |

**Impact:** Screen readers expect an `<h1>` for page orientation.
"Skip to main content," "Headings" navigation modes, and document
outline tools all degrade without it. WCAG 2.4.6 Headings and Labels
isn't strictly violated, but best practice is one `<h1>` per page.

**Fix (single change in `base.html`):**

```diff
- <span class="flex-1 text-center text-sm opacity-80">{% block page_title %}{% endblock %}</span>
+ <h1 class="flex-1 text-center text-sm font-normal opacity-80">{% block page_title %}{% endblock %}</h1>
```

Every per-page `page_title` block already exists (e.g. fan_out.html
defines `{% block page_title %}Fan-out{% endblock %}`); promoting the
wrapper to `<h1>` gives each page exactly one canonical heading.
Visual styling is preserved.

---

### 🟡 MEDIUM-2 — no skip-to-main link

`base.html` renders 49 interactive sidebar elements + global header
chrome before reaching `<main>`. Keyboard-only users currently must
tab through every sidebar entry on every page navigation. A
visually-hidden, focus-visible "Skip to main content" link is the
standard remedy.

**Fix (in `base.html`, immediately after `<body>`):**

```html
<a href="#hm-main"
   class="sr-only focus:not-sr-only focus:fixed focus:top-2 focus:left-2
          focus:z-[60] focus:px-3 focus:py-1.5 focus:bg-accent-strong
          focus:text-white focus:rounded-md focus-visible:ring-2
          focus-visible:ring-accent">
  Skip to main content
</a>
```

The `#hm-main` target already exists (line 262), so no per-page edit
needed.

---

### 🟡 MEDIUM-3 — `_empty_state.html` partial under-used

The partial exists and is well-built (focus-visible, semantic markup,
slot for action button), but only **1 of 15 templates** includes it.

Surfaces that have hand-rolled empty states that should consolidate:

- `dashboard.html`: empty Q&A list, empty recall results, empty
  plugin list
- `network.html`: empty event log, empty graph, empty trajectories
- `project_detail.html`: empty memory list, empty trajectories,
  no-git state
- `dispatcher_trace.html`: empty waterfall

Each currently emits its own `text-foreground-subtle italic …`
markup. Consolidating to `{% include "_partials/_empty_state.html" with msg="..." %}`
keeps copy + tone consistent and centralises future
state-icon / illustration upgrades.

---

### 🟡 MEDIUM-4 — duplicate `/api/*` fetches (T4b carry-over from v21.0.3)

Per `docs/perf-deep-dive-2026-05-11.md`, cold dashboard load fires
**44 fetch requests**, including:

- 6× `/api/projects`
- 6× `/api/network/events`
- 3× `/api/hosts/budget`
- 2× each: `/api/plugins`, `/api/bridge/status`, `/api/trajectories`,
  `/api/ignored-projects`

This was deferred from v21.0.3 because warm responses are now
sub-millisecond. Still worth doing for:

- Cleaner DevTools / network panel (debuggability)
- Battery on mobile
- Setting a good pattern for future endpoints

**Fix:** introduce one `Alpine.store('hmData')` in `base.html` that
owns canonical fetches and exposes derived getters. Each component
becomes a `x-data` over `$store.hmData.projects` instead of its own
`fetch('/api/projects')`. `network.html` already uses the pattern
(`Alpine.store('hmNetTab')` for tab state) — extend it.

Estimated effort: ~3 hours; impact: 44 → ~10 fetches on cold load.

---

### 🟢 LOW-1 — `<style>` in `base.html:94` is redundant

`tailwind.input.css` already sets `body { font-family: var(--font-mono); }`
(line 187). The inline `<style>` block at base.html:94 duplicates this
with a hard-coded `ui-monospace, …` list. Pre-cache, pre-CSS-parse paint
benefits are negligible.

**Fix:** Delete the inline `<style>` block.

The OTHER inline `<style id="hm-custom-accent">` at line 169 is
**intentional** — operator-tunable accent OKLCH mutated at runtime
from localStorage; leave it.

---

### 🟢 LOW-2 — heavy `dashboard.html` (3 063 lines)

The dashboard is by far the largest template. Internal sections:

- Cmd-K palette
- Keyboard shortcuts cheatsheet
- KPI strip with 24h sparklines
- Sidebar wrapper
- Project list / grouped / flat views
- Plugins panel
- Bridge status panel
- Network log panel
- Inspector pane
- Accent color picker
- Operator-tunable model dropdowns
- 5-tab project page

This is the v21 chain's "kitchen-sink" file. Several sections could
extract cleanly into partials without disrupting Alpine state:

- `_partials/_dashboard_kpi_strip.html`
- `_partials/_dashboard_accent_picker.html`
- `_partials/_dashboard_kbd_cheatsheet.html`

Not urgent — 3k-line Jinja templates are fine to maintain in practice
— but extraction makes diff review easier.

---

### 🟢 LOW-3 — narrow breakpoint coverage

Mobile responsive coverage by Tailwind prefix:

- `sm:` — 1 utility
- `md:` — 23 utilities (main responsive switch — drawer collapse below 1024px)
- `lg:` — 7 utilities
- `xl:` — 0 utilities

The `xl:` 0 means no special wide-screen optimizations. On 27"+ monitors
the workspace shell stretches without taking advantage of the extra
width (e.g. could surface inspector content inline rather than in a
collapsible aside). Not a defect — just an opportunity.

---

## Form labels — uneven but covered

```
template                       inputs  <label>  aria-label
base.html                          1       0        14
dashboard.html                    17       5        45
fan_out.html                       6       7         7
network.html                       5       4        11
project_detail.html               11       5        38
_partials/_sidebar.html            2       0         6
_partials/ask_form.html            3       2         3
_partials/delegate_form.html       3       1         3
```

Visual-label coverage looks sparse (24 `<label>` for 48 form controls),
but **aria-label coverage is generous** (136 total). Search boxes,
range sliders for OKLCH, theme toggles, and inline filter fields use
`aria-label` rather than visible `<label>` — defensible for compact
chrome surfaces. Visible `<label>` + form pairing in fan_out.html and
the explicit forms in dashboard is correct.

Not a finding — listed for transparency.

---

## Touch targets — fine

All `px-1 py-0` / `px-1 py-0.5` matches in the audit are `<kbd>` glyph
elements (Esc, Cmd-K, ⌘ hints) or `<output>` displays — **not buttons**.
Real buttons consistently use ≥`px-2 py-1` or `px-3 py-2`. No mobile
touch-target gaps surfaced.

---

## Summary

| Severity | Count |
|---|---:|
| CRITICAL | **0** |
| HIGH | **0** |
| MEDIUM | 4 (`<h1>`, skip link, empty-state reuse, fetch dedup) |
| LOW | 3 (redundant `<style>`, big dashboard template, `xl:` coverage) |

WCAG AA estimate: ~95% (one cluster of medium items, all easy to close).
Compared to the v21.0.0 baseline that shipped a dashboard ReferenceError,
this is excellent shape.

---

## Recommended action plan

### v21.0.4 patch (~1.5 h total)

1. Promote `{% block page_title %}` wrapper to `<h1>` in `base.html` (MEDIUM-1)
2. Add skip-to-main link at top of `<body>` (MEDIUM-2)
3. Delete redundant `<style>` block at `base.html:94` (LOW-1)

### v21.0.5 / future polish (~3 h)

4. Migrate hand-rolled empty states to `_empty_state.html` partial (MEDIUM-3)
5. `Alpine.store('hmData')` to dedupe overlapping fetches (MEDIUM-4)

### v22+ feature work

6. Extract dashboard.html partials (LOW-2)
7. `xl:` widescreen layout pass (LOW-3)

None of these are release-blocking. The codebase is genuinely in
"polish phase" for UI/UX, which is the right place to be after the
v9→v21 chain.

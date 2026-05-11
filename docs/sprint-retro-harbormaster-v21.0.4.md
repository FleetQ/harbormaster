# Sprint Retro — Harbormaster v21.0.4 (patch)

**Released:** 2026-05-11
**Type:** Patch — UI/UX a11y polish from the v21.0.3 audit
**Branch flow:** Directly on `main`

## Why this patch exists

The `/ui-ux-review` audit (`docs/ui-ux-review-2026-05-11.md`) on the
v21.0.3 source tree found 4 medium and 3 low items. v21.0.4 closes
the two a11y-leaning medium items because both fixes are 1-line and
benefit every keyboard / screen-reader operator immediately.

## Fixes shipped

### M1 — promote `{% block page_title %}` from `<span>` to `<h1>`

`base.html`: the per-page page-title slot used to be a `<span>` inside
the topbar, so **no template had any `<h1>`**. Every page now gets
exactly one canonical top-level heading via the existing block.

```diff
- <span class="flex-1 text-center text-sm opacity-80">{% block page_title %}{% endblock %}</span>
+ <h1 class="flex-1 text-center text-sm font-normal opacity-80">{% block page_title %}{% endblock %}</h1>
```

Visual styling preserved: `font-normal` keeps the topbar title at
small/regular weight; only the semantic element changes.

Verified live across surfaces: `Dashboard`, `harbormaster` (project
detail), `Fan-out`, `Network`, `Dispatcher trace` all now render with
`<h1>…</h1>` at the topbar slot.

### M2 — skip-to-main-content link

`base.html`: added a visually-hidden, focus-visible link at the very
top of `<body>` that jumps to the canonical `#hm-main` landmark.

```html
<a href="#hm-main"
   class="sr-only focus:not-sr-only focus:fixed focus:top-2 focus:left-2
          focus:z-[60] focus:px-3 focus:py-1.5 focus:bg-accent-strong
          focus:text-white focus:rounded-md focus-visible:outline-none
          focus-visible:ring-2 focus-visible:ring-accent">
  Skip to main content
</a>
```

Keyboard users on every page navigation can now jump past the topbar
+ sidebar (49+ interactive elements) directly to the main content.
`#hm-main` already exists in `base.html:266`, so no per-page work
needed.

## What I didn't ship (and why)

### L1 deferred — inline `<style>` block in `base.html:94` is NOT redundant

The `/ui-ux-review` report initially flagged the inline `<style>` at
`base.html:94` as duplicating tailwind.input.css's `body { font-family }`
and `[x-cloak] { display: none }` rules. On closer reading, the
block's own comment at line 97-100 says:

> Tailwind v4 @theme block in tailwind.input.css is the primary
> source — these inline tokens are the CDN fallback served when
> /static/tailwind.css is unreachable.

The `body { font-family }`, `[x-cloak] { display:none }`, AND the
v21.0.0a1 mobile drawer `#hm-shell-grid` / `#hm-sidebar` /
`#inspector` rules live inline **on purpose** so the dashboard stays
functional when the compiled Tailwind CSS fails to load (proxy
breakage, CDN miss, etc.). Removing them would break a real
fallback layer. The audit was wrong; this patch leaves the block
intact.

Lesson captured in the audit doc for any future reviewer.

### MEDIUM-3 + MEDIUM-4 deferred

`_empty_state.html` consolidation and `Alpine.store('hmData')` fetch
dedup are larger changes (~3 h combined). They're queued for a future
patch — not release-blocking for v21.0.4.

## Verification

- `ruff check src/ tests/` — clean
- `mypy --strict src/harbormaster/` — clean (58 source files)
- `pytest tests/` — **1888 passed, 1 skipped, 0 failed**
- Live dev UI on `:7541` re-validated — h1 + skip link land on
  `/`, `/projects/<name>`, `/tools/fan-out`, `/network`,
  `/dispatcher/trace`.

## Chain status

Still HALTED. v21.0.4 is the fourth operator-initiated patch in the
2026-05-11 audit cycle. Substantive future work remains a `v22.x`
feature line, not chain resumption.

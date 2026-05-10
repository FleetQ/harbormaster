# Sprint Retro — Harbormaster v8.0.0 (GA)

**Date:** 2026-05-10
**Theme:** Cumulative retro covering the 7-alpha v8.0 UI polish
line. Pure UI surface work — accessibility floor, state-badge
icons, canonical empty states, command palette, KPI strip,
project navigation sidebar, distribution slim-down. Zero
backwards-incompatible changes; every new behavior is additive.

## Tags published

| Tag         | Type      | Capability                                                     |
|-------------|-----------|----------------------------------------------------------------|
| `v8.0.0a1`  | feature   | A11y floor — aria-label/live/busy + focus-visible rings       |
| `v8.0.0a2`  | feature   | State badges gain icon glyph + full aria-label                |
| `v8.0.0a3`  | feature   | Canonical 3-part empty states across 5 surfaces               |
| `v8.0.0a4`  | feature   | Cmd-K command palette with bigram fuzzy match                 |
| `v8.0.0a5`  | feature   | KPI strip atop dashboard + new `/api/kpi` aggregator          |
| `v8.0.0a6`  | feature   | Left navigation sidebar with grouped projects + pinned        |
| `v8.0.0a7`  | feature   | HTMX dropped, semantic OKLCH color tokens added               |
| `v8.0.0`    | GA        | Cumulative — promotion, no new code                           |

## Cumulative numbers

- **Tests:** 797 → 921 collected (+124 new tests; +15.5%)
- **Source files:** 52 → 52 (no change — pure UI surface work,
  one new `_partials/_empty_state.html`, no Python additions
  beyond `QAStore.count_since` + `/api/kpi` route handler in
  existing files)
- **Templates touched:** 6 / 6 (every UI template + 1 new partial)
- **Page weight delta:** -14KB cold-load (HTMX script tag removed
  in a7); +~2KB inline CSS for OKLCH tokens; net **-12KB**
- **mypy --strict + ruff:** clean across all 7 alphas
- **Backwards-incompatible changes:** 0 user-facing
- **Per-phase wall clock:** ~6-12 minutes per alpha; full GA in
  ~70-80 minutes of autonomous work
- **PyPI verification:** a1-a6 confirmed on PyPI before GA (a7 in
  flight at GA bump time; will land within publishing SLA)

## Capability narrative

### Accessibility (a1, a2, a3 contributions)

* Every interactive element carries `focus-visible:ring-*` for
  keyboard focus visibility.
* Every icon-only button declares `aria-label` (or `:aria-label`
  for state-aware labels).
* Every streaming `<pre>` carries `aria-live="polite"`.
* Every `x-show="error"` block declares `role="alert"`.
* Every `<button type="submit">` referencing a `loading` flag
  binds `:aria-busy`.
* Every state badge (bridge, plugins, reembed phase, trajectory
  tier) carries `:aria-label="<surface> <state>"`.
* Every empty-state surface declares `role="status"`.
* `text-gray-500` → `text-gray-400` on every interactive
  secondary-label position (WCAG AA contrast bump).

### Affordance (a3, a4, a5, a6)

* Every "nothing yet" surface ships a 3-part empty state
  (headline + body + CTA) instead of one-line "no matches"
  prose.
* `Cmd+K` / `Ctrl+K` opens a global command palette with fuzzy
  search across projects, tools, pages, help.
* Five glanceable KPIs sit atop the dashboard with 30s
  auto-refresh.
* Left navigation rail with operator-pinned + recently-asked +
  by-language groups, persisted to `localStorage`.

### Distribution (a7)

* HTMX dropped (zero `hx-*` ever in the templates; pure download
  cost removed).
* Semantic OKLCH `--hm-*` tokens defined for forward-compat with
  the v9 Tailwind v4 `@theme` migration.

## Deviations from the plan

### 1 · Phase 7 split: deferred Tailwind v4 vendor + utility migration to v9

**The v8 plan called for "Tailwind v4 + OKLCH semantic tokens +
drop HTMX" in one alpha. We shipped HTMX-drop + OKLCH tokens, and
deferred the full Tailwind v4 vendor + class migration to v9.**

Rationale (also captured in the v8.0.0a7 retro):

* The full migration needs a distribution-path decision — vendor
  the standalone `@tailwindcss/cli` binary (~10MB extra wheel)
  vs. add a build step to `pyproject.toml` (smaller wheel, slower
  install on air-gapped boxes). Without explicit operator input
  on the trade-off, picking unilaterally would set a precedent
  we can't easily reverse.
* ~150 utility-class rewrites across 5 templates need visual
  confirmation. Without a Playwright screenshot-diff harness we
  can't verify color correctness post-rewrite. The harness itself
  is a pre-req for safe migration.
* The CDN-removal/CSS-add ordering matters for a one-shot release
  — wrong sequencing = blank dashboard.

This is the explicit escape hatch the phase plan authorised:
*"User authorized 'all in one alpha' but if it genuinely won't
fit, split with explicit note in retro."*

### 2 · Sidebar's collapse-state for desktop not shipped

The v8.0.0a6 plan called for a per-operator `localStorage`-
persisted desktop collapse state on the sidebar itself
(collapsed/expanded). What shipped: per-language-group collapse
state, but no top-level rail collapse. The per-group toggle gives
finer-grained control than a binary rail-collapse, so this defers
naturally. Will revisit if operators ask for the rail-collapse
binary toggle.

### 3 · Sidebar's archived group not shipped

The plan listed an "Archived" group (last commit > 90 days OR
operator-marked). The auto-detect path needs a `last_commit_age`
field on `ProjectInfo` that doesn't exist; the operator-marked
path needs a per-project flag we don't store. Defer to v9 with
the multi-host enhancements.

## Confirmation: HTMX removal

* `grep -rn 'hx-' src/harbormaster/ui/templates/` → 0 matches
  (audit lives in `tests/ui/test_phase7_distribution.py`).
* `<script src="https://unpkg.com/htmx.org@1.9.10">` removed from
  `base.html`.
* `tests/unit/test_ui.py::test_root_returns_dashboard_html`
  flipped from `assert "htmx" in body` to `assert "htmx" not in
  body`. Documented at the assertion site with the removal
  rationale.
* Page weight: -14KB on cold load (one less script download,
  ~14KB minified+gzipped).

## Confirmation: Tailwind v4 distribution path

**Distribution path chosen for v8.0.0:** none — Tailwind v3 CDN
remains the active stylesheet source. Semantic OKLCH tokens
defined inline as CSS custom properties (`--hm-*`) under `:root`
in `base.html` for forward-compat.

**Distribution path deferred to v9:** to be decided with the
operator. Two options on the table:

  (a) Vendor the `@tailwindcss/cli` standalone binary into
      `vendor/` — operators pay no Node toolchain cost, wheel
      grows by ~10MB.
  (b) Add a CSS build step to `pyproject.toml` — wheel stays
      small, but `uvx harbormaster-mcp` install slows by the
      build time.

The OKLCH tokens are placed precisely so the eventual `@theme`
block can lift them literally — no value re-derivation needed.

## v9 candidate list (compiled from the 7 sprint retros)

Ordered by priority hint from the retros (highest first):

1. **Tailwind v4 vendor + utility migration** (a7 retro top item).
   Pre-req: Playwright screenshot-diff harness.
2. **Trace waterfall surface** (original v8 phase plan; reserved
   for v9 throughout).
3. **Per-host KPI rollup** (a5 retro). Multi-host query counts in
   the KPI strip.
4. **`/api/dispatcher/status`** (a5 retro). Replace the hardcoded
   "ready" placeholder with a real dispatcher state model.
5. **Sidebar enhancements** (a6 retro):
   * Top-level rail collapse with `localStorage` persistence.
   * Archived group (auto-detect via `last_commit_age` + manual
     mark).
   * Per-host project filter.
6. **Light-mode token branch** (a7 retro). Add a
   `[data-theme="light"] :root { … }` overlay to the OKLCH token
   block.
7. **`stateBadge(state)` helper unification** (a2 retro). One
   helper per state-discriminating badge instead of three
   (`*Icon`, `*Label`, `*BadgeClass`).
8. **Snapshot tests for empty states** (a3 retro). Tighter
   contract than substring assertions.
9. **Palette dynamic-action search** (a4 retro). "Ask {project}
   {question}" inline action instead of navigate-then-ask.
10. **Sidebar bigram fuzzy match** (a6 retro). Currently substring;
    bigram only if operators report typo issues.
11. **Mermaid → Cytoscape graph upgrade** (deferred from v7
    sprint retro; reiterated in v8 phase plan).
12. **SSE Last-Event-ID resumption + typed SSE events** (deferred
    from v7 sprint retro).
13. **Trajectory waterfall — pre-cursor work toward (2)**.
14. **Dependency audit follow-up** items deferred from earlier
    sprints (per-version retros).

## What worked across the whole sprint line

* **Audit-test-per-phase as the architectural backbone.** Every
  phase shipped a static template-walk audit. The next template
  edit that drops an aria-label / icon glyph / empty-state class
  fails CI before the PR description gets written. Cumulative:
  124 new tests, all running in <1s, zero browser dependency.
* **Inverted-pyramid retro structure.** Every phase retro leads
  with the 1-line theme + capability table. Reading 7 retros in
  sequence is fast because the first 5 lines tell you what
  shipped.
* **Skip-PR-default flow proven again.** 7 phases × (branch →
  push → checkout main → merge --no-ff → bump+retro → tag →
  push --tags) shipped without a single PR. The push-as-backup
  before merge means we can recover from any local mishap.
* **Soft-fail per source on aggregator endpoints.** `/api/kpi`
  catches per-source errors so missing extras (`[history]` not
  installed) don't 500 the whole endpoint. Same pattern earlier
  routes used; canonicalised here.
* **OKLCH-now, theme-migration-later.** Defining tokens in OKLCH
  unblocks the v9 work without forcing the build-pipeline
  decision now. Same pattern as Phase 4's deferred recent-commands
  history (localStorage write capability staged but not used).

## What we'd do differently next sprint line

* **Add a Playwright screenshot-diff harness early in v9.** The
  v8 line dodged visual regression by being purely additive.
  v9's Tailwind v4 utility migration breaks that constraint;
  visual confirmation needs a regression test, not a manual
  squint.
* **Stage cumulative-test-count metric in CI.** Each phase retro
  reports the diff (`797 → 814 collected`) but the running
  cumulative ("v7 baseline → v8 GA: +124 tests") is calculated
  by hand each time. A small `pytest --collect-only | wc -l`
  step in CI plus a stored baseline would surface drift
  automatically.
* **Distribute the Tailwind v4 distribution-path decision before
  v9 starts.** The v8.0.0a7 split caught us because (a) and (b)
  in the v9 candidate list both have real-world cost
  trade-offs that need explicit operator input. Asking before
  v9-Phase-1 starts saves a mid-phase block.

# Sprint Retro — Harbormaster v9.0.0 (GA)

**Date:** 2026-05-10
**Theme:** Cumulative retro covering the 6-alpha v9.0 architectural-moves
line. Build infrastructure, observability surface, SSE protocol
hardening, and final UI polish before GA. Zero backwards-incompatible
changes; every new behavior is additive (legacy `chunk` SSE event
deprecated for one full version).

## Tags published

| Tag         | Type    | Capability                                                                |
|-------------|---------|---------------------------------------------------------------------------|
| `v9.0.0a1`  | feat    | Tailwind v4 vendor + build hook (closes v8 a7 deferral)                   |
| `v9.0.0a2`  | feat    | `/api/dispatcher/status` real endpoint + dispatcher CLI `--url` flag      |
| `v9.0.0a3`  | feat    | Trace waterfall surface (`/dispatcher` page + SSE event stream)           |
| `v9.0.0a4`  | feat    | SSE Last-Event-ID resumption + per-event id assignment                    |
| `v9.0.0a5`  | feat    | Typed SSE events (`token`, `usage`) alongside legacy `chunk`              |
| `v9.0.0a6`  | feat    | Sidebar polish (archived + rail-collapse + host filter) + palette dynamic-action |
| `v9.0.0`    | GA      | Cumulative — promotion, no new code                                       |

## Cumulative numbers

* **Tests:** 921 → 1017 collected (+96 new tests; +10.4%)
* **Source files:** 52 → 52 (no new modules; helpers added inside existing files; `build_tailwind_css.py` lives at repo root, not under `src/harbormaster`)
* **Templates touched:** 3 (`base.html`, `dispatcher_trace.html` new, `_partials/_ask_form_script.html`)
* **New routes:** 4 (`GET /static/{path}`, `GET /api/dispatcher/status`, `GET /api/dispatcher/recent`, `GET /api/dispatcher/trace`, `GET /dispatcher`)
* **New SSE event types:** 4 (`token`, `tool` wire-format-only, `usage`, `span_start`/`span_end`)
* **mypy --strict + ruff:** clean across all 6 alphas
* **Backwards-incompatible changes:** 0 user-facing
* **Per-phase wall clock:** ~10-20 minutes per alpha; full GA in ~120 minutes of autonomous work
* **PyPI verification:** verification poll runs in background after each tag push

## Capability narrative

### Build infrastructure (a1)

* Tailwind v4 ships pre-compiled in the wheel via a hatchling
  custom build hook. End users still install with
  `uvx harbormaster-mcp` — zero Node toolchain.
* The `@theme` block lifts v8.0.0a7's `--hm-*` OKLCH tokens into
  first-class `--color-*` Tailwind values; legacy aliases
  preserved for external CSS consumers.
* New `GET /static/{path}` route serves packaged assets via
  `importlib.resources.files` (works in zipped wheels).

### Live observability (a2, a3)

* `DispatcherStats` singleton (a2) records per-tool counters
  (`in_flight`, `total_completed`, `total_failed`) + in-flight
  spans + `last_dispatched_at`. Thread-safe; ~2 lock acquires
  per dispatch.
* `GET /api/dispatcher/status` exposes the canonical schema
  used by both the KPI strip (replaces v8 hardcoded "ready"
  placeholder) and the new trace surface.
* Trace surface (a3) ships at `GET /dispatcher`: live
  in-flight spans + last-100 completed spans rendered as a
  single-row timeline (parent/child waterfall reserved for
  v10's potential D3/Cytoscape upgrade).
* `GET /api/dispatcher/trace` SSE stream emits typed `span_start`
  / `span_end` events with monotonic `span_id` and SSE `id:`
  lines for browser-native reconnect.

### SSE protocol hardening (a4, a5)

* Every SSE event across the dashboard's streaming surfaces
  carries an `id:` line (a4). Trace events use `span_id`
  directly; per-request streams (`_emit_chunks_then_result`,
  `_stream_dispatch`) get monotonic per-stream ids via
  `_StreamIdSeq`.
* `Last-Event-ID` request-header parse on `/api/dispatcher/trace`
  triggers ring-buffer replay of any completed spans with
  `span_id > last`, then resumes the live tail.
* Typed events (a5): every text delta now emits BOTH `chunk`
  (legacy) AND `token` (new). The `chunk` event is DEPRECATED
  and removed in v10. New `usage` event lands just before
  `result` carrying best-effort output counts.

### UI polish (a6)

* Sidebar Archived group: projects with `last_commit_age_days >= 90`
  collapse into a dedicated section, hidden by default.
* Sidebar rail-collapse: 240px → 48px chevron toggle, persisted in
  localStorage. Main content margin reflows automatically.
* Sidebar per-host filter: dropdown showing `__all__` + `local` +
  any remote labels detected on `/api/projects`.
* Palette dynamic-action: `Ask <project> <question>` inside Cmd-K
  composes a navigate-with-prefilled-query action.

## Cumulative deviations from the plan

### Phase 1: utility-class migration deferred

The original v9.0.0a1 spec called for migrating ~150 utility
classes from raw color names (`bg-cyan-700`) to semantic-token
classes (`bg-accent`). The phase plan authorized splitting if
scope explodes; we shipped the build infrastructure + token defs
+ vendored stylesheet only. The migration is reserved for a
v9.0.0a1.5 follow-on (or v10) once a screenshot-diff harness lands.

### Phase 3: parent/child waterfall → single-row timeline

The trace surface from v9.0.0a3 renders one bar per dispatch, not
a tree of parent/child spans. True parent/child instrumentation
needs backend-side tool-call emission (a v10 candidate alongside
real OpenTelemetry SDK integration). The single-row timeline is
visually informative + ships the SSE event format that v10's tree
view will consume unchanged.

### Phase 4: client-side exponential backoff not implemented

The plan called for `1s, 2s, 4s, max 8s` reconnect backoff with
3-attempt cap. Browser-native `EventSource` reconnect already
handles the common case (and now leverages `Last-Event-ID` for
catch-up). Custom backoff requires a fetch-based EventSource shim
across all consumers — deferred to v10.

### Phase 5: real token counting deferred

The `usage` event ships `output_chunks` + `output_chars` with an
`approximate: true` flag. Real `input_tokens` / `output_tokens` /
`model` need backend-side instrumentation (Claude CLI / Codex
CLI) which is a v10 phase line of its own.

### Phase 6: stateBadge helper unification deferred

Pure refactoring with no observable user value, low risk to v9
GA. Reserved for v10's template-quality pass.

## Confirmation: Tailwind v4 build step working

* `uv build` produces a clean wheel (5224-byte minified
  `tailwind.css` shipped under `harbormaster/ui/static/`).
* The build hook `build_tailwind_css.py` runs `npm install` of
  `tailwindcss` + `@tailwindcss/cli` into a temp prefix, symlinks
  `node_modules` next to the input CSS, runs the CLI minified,
  verifies the canonical `--color-accent` probe token survived
  compilation, then cleans up.
* When `npx` is missing (Node-less CI doing sdist builds), the
  hook warns and trusts the committed `tailwind.css` as-is.

## Confirmation: SSE backwards-compat (chunk events still emitted alongside token)

* Server: every text delta in `_emit_chunks_then_result` yields
  TWO SSE events — `chunk` (data: `{"text": ...}`) AND `token`
  (data: `{"delta": ...}`).
* Client: `_partials/_ask_form_script.html` listens for both,
  prefers `token` via a `preferTokenEvents` flag (no
  double-counting), keeps the legacy `chunk` handler for
  backwards-compat with consumers that haven't migrated.
* Old tests asserting `[chunk, chunk, result]` updated to
  `[chunk, token, chunk, token, usage, result]` — explicit
  contract-test catching catches future refactors that drop
  either event type.
* The `chunk` event is removed in v10 alongside the
  `preferTokenEvents` flag.

## What worked across the whole sprint line

* **Audit-test-per-phase as the architectural backbone.** Every
  phase shipped a static template-walk audit. The next template
  edit that drops an aria-label / icon glyph / new event type /
  Alpine helper fails CI before the PR description gets written.
  Cumulative: 96 new tests, all running in <1s except the SSE
  stream tests (which use direct generator probes rather than
  TestClient.stream to avoid the documented blocking-iter issue).
* **Inverted-pyramid retro structure.** Every phase retro leads
  with the 1-line theme + capability table. Reading 6 retros in
  sequence is fast because the first 5 lines tell you what shipped.
* **Skip-PR-default flow proven again.** 6 phases × (branch →
  push → checkout main → merge --no-ff → bump+retro → tag →
  push --tags) shipped without a single PR. The push-as-backup
  before merge means we can recover from any local mishap.
* **Singleton + thread-safe metrics for sidecar observability.**
  v9.0.0a2's `DispatcherStats` was the foundation everything else
  built on (a3, a4, a5 all consume the same singleton). The lock
  scope was right the first time — no concurrency bugs through
  six phases of additions.
* **Dual-emit + client preference flag for protocol migrations.**
  v9.0.0a5's `chunk`/`token` coexistence, removable in one v10
  commit, is the cleanest no-breaking migration we've shipped. The
  pattern generalizes.
* **OKLCH-now, theme-migration-later (continued from v8).** The
  v8 retro called this out as the right call; v9 confirmed it by
  keeping the CDN script alive while the vendored stylesheet
  ships token defs only. Nothing visually regresses; the
  migration alpha (v9.0.0a1.5 or v10) gets a clean canvas.

## What we'd do differently next sprint line

* **Land the screenshot-diff harness early in v10.** v9 dodged
  visual regression by being purely additive. The deferred
  Tailwind utility-class migration breaks that; visual
  confirmation needs a regression test, not a manual squint.
  Phase 1 of v10.
* **Document the localStorage key namespace.** v8 + v9 have grown
  ~6 keys under `hm:sidebar:*` and `hm:cmdk:*`. A short cookbook
  in `docs/operator/ui-state.md` would help operators reset state
  in bulk.
* **Add a Playwright integration test for the dispatcher trace
  surface.** The unit-level template-walk audit + DispatcherStats
  unit tests catch most regressions, but a real-browser test
  would catch Alpine-binding errors (e.g., live-bar widths not
  updating). Use the v3.0.0a10 `-m browser` opt-in pattern.
* **Backend-side token counter instrumentation.** v9.0.0a5's
  `usage` event is approximate; v10 should land the real
  `{input_tokens, output_tokens, model}` payload by parsing the
  Claude/Codex CLI's own accounting output (or adding
  `--output-format json` to backend invocations).

## v10 candidate list (compiled from the 6 sprint retros + reserved items)

Ordered by priority hint from the retros (highest first):

1. **Screenshot-diff harness** (a1 + cumulative retro). Pre-req
   for the deferred utility-class migration.
2. **Tailwind v4 utility-class migration** (a1 deferral). ~150
   rewrites across 6 templates from raw color names to semantic
   `--color-*` classes.
3. **Backend-side token counter instrumentation** (a5 deferral).
   Drops the `approximate: true` flag; surfaces real
   `input_tokens` / `output_tokens` / `model` in the usage event.
4. **`stateBadge(state)` helper unification** (a6 deferral, also
   v8 candidate). Three call sites consolidated.
5. **Trace waterfall true parent/child viz** (a3 deferral).
   Backend tool-call instrumentation + a v10 D3 / Cytoscape view.
6. **`?q=<question>` URL pre-fill on the project page** (a6
   deferral). 5-line follow-up to make the palette dynamic-action
   end-to-end seamless.
7. **Light-mode token branch** (carried forward from v8). Now
   feasible because v9.0.0a1's `@theme` block is the canonical
   token home.
8. **Mermaid → Cytoscape graph upgrade** (carried forward).
9. **Schema versioning for `dispatcher status --json`** (carried
   forward from v8).
10. **Linguist-style language detection fallback** (carried
    forward).
11. **Cross-process projects cache** (carried forward).
12. **Snapshot tests for empty states** (carried forward).
13. **Lint Alpine x-data for unhandled-promise patterns** (carried
    forward; combine with #4).
14. **Custom fetch-based EventSource shim** (a4 deferral). Unifies
    reconnect strategy across all SSE consumers.
15. **Removal of legacy `chunk` SSE event + `preferTokenEvents`
    flag** (a5 deprecation timeline).
16. **Operator docs: `localStorage` key cookbook** (cumulative
    retro lesson).
17. **Per-host KPI rollup** (carried forward from v8).
18. **Multi-process metrics aggregator** (a2 lesson — the
    singleton is process-scoped; remote harbormaster-mcp +
    harbormaster-ui have separate counter sets).

## Operator note for v9.0.0 upgrade

* Hard-reload the dashboard (Cmd-Shift-R / Ctrl-Shift-R) on first
  visit after upgrade. The cached `base.html` from v8 references
  the v3 CDN only; the v9 sheet adds the vendored
  `<link rel="stylesheet" href="/static/tailwind.css">` that
  defines the `@theme` tokens.
* New SSE event types coexist with legacy ones — no client-side
  changes required for existing dashboards.
* The dispatcher trace surface (`/dispatcher`) is opt-in (link in
  the nav bar); it doesn't auto-load on the dashboard, so first-
  visit experience is unchanged.

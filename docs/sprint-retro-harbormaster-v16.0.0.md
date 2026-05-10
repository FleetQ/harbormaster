# Sprint Retro — Harbormaster v16.0.0 (GA)

**Date:** 2026-05-10
**Theme:** Cumulative retro for the v16 sprint — six alphas + GA in
one autonomous session. Internal quality cluster + pre-commit polish
+ tour wizard hardening + diff/comparison viz polish + per-project
budget + trace waterfall backend instrumentation (split-shipped).

## Tags published

| Tag | Headline |
|-----|----------|
| `v16.0.0a1` | Internal quality cluster — autouse network_log fixture + cachedGetter Alpine helper + `_make_parser` markdown helper |
| `v16.0.0a2` | Pre-commit polish — `pre-commit` in `[dev]` extra + `post_sync_install_hooks.sh` + doc-parity suggested-edit emitter |
| `v16.0.0a3` | Tour wizard hardening — `data-tour-step` markup attrs + 3-step `/network` tour |
| `v16.0.0a4` | Diff/comparison viz polish — `/api/config/diff?format=html` (HtmlDiff) + tiny SVG sparkline helper |
| `v16.0.0a5` | Per-project budget — third axis of the budget triad with tightest-cap-wins arithmetic |
| `v16.0.0a6` | Trace waterfall — backend instrumentation slice (parent_span_id + trace_id + span_context). Split executed; renderer deferred to v17 |
| `v16.0.0` (this) | GA — cumulative retro + tag |

## Cumulative numbers

- **Tests**: 1522 → 1593 (+71 net new tests across the six alphas)
- **Source files**: 57 → 57 (no new modules — every alpha extended
  existing files; new files landed under `_partials/`,
  `scripts/`, `examples/`, and `docs/` only)
- **Wall-clock**: ~2.5 hours autonomous, six branches → main → tags
- **Commits**: 6 feature merges + 6 ship commits
- **Lint / type**: ruff clean every alpha, `mypy --strict` clean
  every alpha
- **Backwards-incompatible changes**: 0
- **Confirmation: did NOT touch `.github/workflows/*`**: yes —
  zero workflow changes; pre-commit work (a2) extended the v15.a5
  surface entirely at repo root + `scripts/`.

## Per-phase wall-clock (rough)

| Phase | Wall-clock | Net tests |
|-------|------------|-----------|
| v16.a1 (quality cluster) | ~25 min | +13 |
| v16.a2 (pre-commit polish) | ~20 min | +9 |
| v16.a3 (tour hardening) | ~25 min | +9 |
| v16.a4 (diff/comparison viz) | ~25 min | +15 |
| v16.a5 (per-project budget) | ~25 min | +12 |
| v16.a6 (trace waterfall backend) | ~35 min | +13 |
| GA | ~10 min | — |

## What worked across the sprint

- **Mirror, don't invent.** Every alpha had a structural analogue
  in v14 / v15. The cachedGetter helper unified two pre-existing
  idioms; the per-project budget mirrored `/api/tools/budget` (v15.a4);
  the side-by-side HtmlDiff mirrored v13.a3's memory-revisions
  toggle; the network tour mirrored v15.a6's dashboard tour;
  v16.a6's span_context mirrored v15.a4's per-tool budget binding.
  Tests, docs, and template wiring followed by analogy. Zero
  design churn.
- **CWD discipline finally locked in.** v15 still had 4 lapses;
  v16 had **0**. The harness auto-sets the worktree CWD on every
  Bash call so a discipline-by-not-doing-anything-extra approach
  works. Documenting "no `cd` calls needed" was enough.
- **Symbol-first exploration via Serena.** `find_symbol` +
  `get_symbols_overview` cut full-file reads dramatically. The
  v16.a6 dispatcher work used `find_symbol("DispatcherStats")`
  + `find_symbol("_RunningSpan")` to land the model changes
  without re-reading the 500-line file.
- **Doc-parity gate kept v16.a5 honest.** The new
  `HostConfig.projects` field hit the v15.a5 parity gate on the
  first pre-test run; v16.a2's suggested-edit emitter would
  also have rendered the row template (didn't need it but the
  safety net was there).
- **Authorised split executed cleanly.** v16.a6 stopped at
  backend instrumentation + SSE event format — clean release
  boundary, low blast radius, every new field additive. v17
  inherits a single well-scoped frontend task instead of a
  half-finished refactor.

## What to change for the next sprint (v17)

- **Trace waterfall renderer** is now the top v17 candidate
  (carry-over from v16.a6 split). Backend already emits the right
  events; the renderer needs to group by trace_id, indent
  children under parents, and bar-width by relative duration.
- **CI workflow autobootstrap** still requires operator OAuth
  token rotation for `workflow` scope (v14 candidate #1, deferred
  again under binding lesson #5).
- **Sparkline integration**: v16.a4 shipped the `sparklineHtml`
  helper but no UI yet consumes it. The v15.a4 N-way reembed
  comparison endpoint is the natural target — needs a small
  client-side panel that renders per-cell trend cells.

## Cumulative session totals (v3 + v4 + v5 + v6 + v7..v16)

Numbers from v16 only (other lines tracked in their own retros):

- **PyPI versions shipped this sprint**: 7 (a1-a6 + GA)
- **6 feature merges + 6 ship commits + 0 force-pushes** to main
- **0 PRs opened** (skip-PR-default invariant maintained)
- **0 breaking changes**
- **57 source files** (unchanged from v15 — extension-only sprint)

## v17 candidate list

Carry-overs from v16:

1. **Re-land the screenshot autobootstrap CI workflow** — needs a
   token with `workflow` scope. (v14 carry-over #1, deferred again
   under v15+v16 binding lesson #5.)
2. **Trace waterfall renderer** — group spans by `trace_id`,
   indent children under parents, bar-width proportional to
   span duration / trace total duration. Hover surfaces project
   + tool + duration. (v16.a6 split carry-over.)
3. **Wire the `sparklineHtml` helper into the N-way reembed
   comparison panel** — the v16.a4 helper exists but no UI
   consumes it. The natural site is per-cell trend rendering
   for `[duration_seconds, total, succeeded, failed, cancelled]`.
4. **N-way reembed compare UI** — the v15.a4 endpoint exists
   but no dashboard panel consumes it. Once #3 lands, this
   becomes a small Alpine factory that fetches the endpoint
   and renders per-cell sparklines.
5. **`tightest_cap` KPI strip cell hover tooltip** — surface
   the v16.a5 per-axis breakdown (`tightest_cap_axis`) on the
   per-host cell so operators see which axis is bottlenecking
   without opening the projects-budget endpoint.
6. **Codex backend tool_use instrumentation parity** — v16.a6
   instrumented `claude.py` only. Codex doesn't emit
   tool_use blocks in its current stream format; once it does
   (or once we wire it via a shim), child spans should fall
   out for free.

## Out-of-scope for v17 (v18+)

- Tauri / Electron desktop UI
- Relay-binary path (Path B)
- IDE extension
- Session-cookie auth + CSRF (orthogonal to v16 surfaces)
- pnpm v5 lockfile
- Cross-process file locking
- LLM extraction for remote hosts
- Cross-model vector translation
- Cross-host trace federation (would need a trace store, not
  the current ring buffer)

## Halt assessment

- **Continue indefinitely while ≥1 candidate exists** — operator
  authorisation invariant. 6 candidates remain; v16 closed 9 of
  the 12 v15 carry-overs and surfaced 4 new ones (waterfall
  renderer, sparkline UI integration, N-way compare UI,
  tightest_cap tooltip). #1 (CI workflow) is the long-running
  carry-over still blocked on operator action.
- **No brand-new requirements surfaced** that would force a halt.
- **Test suite green** (1593 pass + 3 skips + 4 deprecation
  warnings unchanged from v15), lint clean, no breaking changes —
  release bar met.
- **Did NOT touch `.github/workflows/*`** — confirmed.

Recommend: **continue to v17** when authorised. v17 has 6
candidates to slot into a 4-5 alpha shape; the trace waterfall
renderer (the v16.a6 split carry-over) is the natural opener.

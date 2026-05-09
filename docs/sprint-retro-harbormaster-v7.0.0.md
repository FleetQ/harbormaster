# Sprint Retro — Harbormaster v7.0.0 (GA)

**Date:** 2026-05-09
**Theme:** GA — six alphas in one autonomous session, regression
guards for the v6 graph bug class, operator control over reembed
runs, and dashboard polish. Every alpha shipped to PyPI without
human intervention; this retro summarises the cumulative work and
extracts the v8 candidate list from the per-alpha retros.

## What landed (cumulative)

### `harbormaster` (this repo) — 6 alpha tags + GA

| Tag | Subject |
|-----|---------|
| `v7.0.0a1` | Browser SVG-render assertion (Playwright bbox check) |
| `v7.0.0a2` | Static template safety audit (html.parser walk + ALLOWLIST) |
| `v7.0.0a3` | Cancel-running-reembed button + cooperative cancel flag |
| `v7.0.0a4` | Rolling reembed run-history log + UI table |
| `v7.0.0a5` | `--json` output for `harbormaster-mcp dispatcher status` |
| `v7.0.0a6` | Language badge on dashboard cards + ProjectsCache TTL memo |
| `v7.0.0`   | GA tag (no new code; this retro + version bump) |

## Capabilities (sprint summary)

The 6 alphas split cleanly into three buckets:

  1. **Regression guards (a1, a2)** — close the v6.0.0/6.0.1/6.0.2
     graph-render detection gap with both a runtime Playwright
     assertion and a static template audit. Both are scoped narrowly
     to the bug class; ALLOWLIST'd safe patterns are documented.
  2. **Operator control over reembed (a3, a4)** — cancel button +
     cooperative cancel flag, plus a rolling 50-record history log
     surfaced via `GET /api/history/reembed/runs` and a collapsible
     UI table. Both ship the v6 retro candidates that operators
     asked for.
  3. **Polish + scriptability (a5, a6)** — `--json` for the
     dispatcher status CLI (no new behavior, additive flag);
     language badge on cards (read v6.0.0a3's `ProjectInfo.language`
     field that previously had no UI surface); TTL cache for the
     `/api/projects` walk.

## Real numbers (cumulative)

- 6 alpha tags + 1 GA tag, all published to PyPI without manual
  intervention
- Test suite delta: **739 → 776 unit tests** (+37 new tests across
  the 6 alphas) — plus 1 new Playwright assertion (the v7.0.0a1
  bbox check) and the v7.0.0a6 dashboard helper assertion
- Source files: **50 → 52** (+1 manifest_cache.py, +1
  reembed_history.py)
- mypy --strict: clean throughout (zero suppressions, zero new
  type:ignore)
- ruff: clean throughout (auto-fixed 3 import-order nits across
  the sprint, no manual rule disables)
- Backwards-incompatible changes: **0 across the entire 6-alpha sprint**

## What worked

- **One sprint retro per alpha.** Forced thinking about what shipped
  vs. what was deferred; surfaced the dispatcher-CLI scope deviation
  in v7.0.0a5 explicitly instead of silently dropping it.
- **Static + runtime guards in pairs.** v7.0.0a1 (runtime Playwright)
  + v7.0.0a2 (static html.parser audit) catch the same bug class
  from different angles. The static audit runs in <100ms on every
  test pass; the Playwright catches the runtime case the static
  audit can't reason about (JS flips the flag in the right order).
- **JS/Python lock-step via test, not docs.** The
  LANGUAGE_BADGE_CLASSES test fails on drift between the JS dict
  (in dashboard.html) and the Python dict (in manifest_cache.py).
  No "remember to update both" comment needed — the test enforces it.
- **Skip-PR-default workflow at this scale.** 6 phases in one
  session × `git checkout main && git merge --no-ff` is faster
  than 6 PR rounds and zero loss of git provenance — the merge
  commits encode "this came from `feat/v7.0-<phase>` on date X".
- **Background CI/PyPI poll.** Verified a1 publishing while moving
  to phase 2; never sat in a sleep-then-check loop.

## What to change / next

- **Fired `git add -A` once and accidentally committed an unrelated
  file.** During v7.0.0a5 ship, `git add -A` picked up a
  `claudedocs/research_harbormaster_ui_ux_2026-05-09.md` that another
  process had created in the working tree. Already in the v7.0.0a5
  tag — can't amend. Rule for v8: stage individual files explicitly,
  never `-A`, when the working tree may contain unrelated state.
- **Phase 5 scope had to deviate.** The plan called for runtime
  metrics (running, queue_depth, active_workers, last_dispatched_at)
  but the dispatcher is in-process and stateless from the CLI's
  perspective. Deviation recorded in the v7.0.0a5 retro; runtime
  metrics surfaced as a v8 candidate.
- **Worktree gitconfig drift.** The first phase commit accidentally
  added `.claude/worktrees/...` as an embedded git repo (gitlink
  rather than ignored path). Fixed in a follow-up commit; for v8,
  add `.claude/` to the global gitignore template before any sprint
  starts.

## v8 candidate list (extracted from the 6 retros)

Carried forward from "Out-of-scope (still)" and "What to change" sections:

1. **Sidecar dispatcher metrics endpoint.** Expose `running`,
   `active_workers`, `queue_depth`, `last_dispatched_at` so
   `dispatcher status --json` can include real runtime state
   (deferred from v7.0.0a5).
2. **Lint Alpine `x-data` for unhandled-promise patterns.** Sister
   to the v7.0.0a2 audit; catch `async () =>` bodies that don't
   await.
3. **Per-host duration tracking in reembed history.** Current record
   only stores outer-run duration. Per-host would need a richer
   state-file format (deferred from v7.0.0a4).
4. **Linguist-style language detection fallback.** A repo with no
   manifest gets `unknown` and no badge. Add file-extension
   heuristics for higher hit rate (deferred from v7.0.0a6).
5. **Cross-process projects cache.** UI and MCP currently each hold
   their own `ProjectsCache`. Worth shared state if a v8 use case
   surfaces (deferred from v7.0.0a6).
6. **Visual regression for the badge colors.** Pixel diffs would
   confirm the lockstep test isn't lying. Maintenance > value at
   our scale today; revisit if a Tailwind upgrade flips colors
   silently (deferred from v7.0.0a6).
7. **Schema versioning for `dispatcher status --json`.** Premature
   at one field set; add when we make a breaking shape change
   (deferred from v7.0.0a5).

## Out-of-scope (still)

- Mid-host cancel for reembed — would require rewriting
  `QAStore.reembed()` to accept a callback; not worth it (single
  hosts complete in <1s).
- Graphical run-history visualisation — table is enough; deferred
  perpetually unless we get a chart-heavy sprint going.
- Full visual regression for the entire dashboard — same maintenance
  argument as the badge case.

## Authoring notes

- 6 phases in 1 session: each phase took ~10 minutes wall clock end-
  to-end (branch → implement → test → lint → commit → push → merge →
  bump → retro → tag → push). The longest was Phase 4 (history log)
  at ~15 minutes due to the extra integration with the runner.
- Total session length: ~90 minutes from "Phase 1 first" to GA tag.
- Zero CI failures, zero rebases, zero conflicting branches across
  the 6 phases (each phase touched a different module).

# Sprint Retro — Harbormaster v7.0.0a6

**Date:** 2026-05-09
**Theme:** Polish + perf. Two related v7 candidates — language badge
on cards (visual, low-effort) and TTL cache for /api/projects (perf
on 20+ project installs) — consolidated into one phase per the
v7.0 plan to keep the alpha cadence tight.

## What landed

### `harbormaster` (this repo)

| SHA | Subject |
|-----|---------|
| (merge) | feat(ui): language badge on dashboard cards + ProjectsCache TTL memo |

## Capabilities (this sprint)

### 1 · `ProjectsCache` — TTL + mtime memo for `/api/projects`

New module `src/harbormaster/ui/manifest_cache.py` (named for the
phase plan — distinct from `harbormaster.graph.cache.ManifestCache`,
which memoises `ProjectManifest` for the dependency graph).

Schema:

```python
ProjectsCache(ttl_seconds: float = 60.0)
  .get(builder, project_dirs) -> list[dict]
  .invalidate() -> None
  .hits, .misses (int)
```

Lock-protected: concurrent dashboard polls share one rebuild rather
than each running their own. The cache stores the previously-
discovered project dirs as its mtime signature; renames/deletes
invalidate immediately, fresh adds surface on TTL expiry (60s).

For installs with 20+ projects this drops `/api/projects` latency
from "git log + manifest detection across every dir, every poll" to
"single dir-stat per dir per request" inside the TTL window.

### 2 · Language badge on dashboard cards

Reads `ProjectInfo.language` (added in v6.0.0a3) and renders a
colored pill on each card. Color table:

  - python → blue
  - typescript / javascript → yellow
  - php → purple
  - rust → orange
  - go → cyan
  - ruby → rose
  - unknown → gray (badge hidden via `x-show`)

The Python `LANGUAGE_BADGE_COLORS` dict and the JS
`LANGUAGE_BADGE_CLASSES` object are mirrored intentionally — a
unit test (`test_language_badge_classes_match_python_table`)
enforces lock-step so a future addition in one place fails the
suite if the other lags.

## Real numbers

- 1/1 v7.0.0a6 phase action items shipped (consolidated 2 candidates)
- 1 feature branch merged (no PR)
- 26 new unit tests + 1 new Playwright assertion (754 → 776 collected;
  +1 source file → 52 total)
- mypy --strict + ruff: clean
- Backwards-incompatible changes: 0

## What worked

- **Lock-stepping JS + Python via test, not docs.** A note in the
  source saying "remember to update both" is wishful thinking. A
  test that fails on drift makes the invariant load-bearing.
- **Cache signature using previously-discovered dirs.** Sidesteps
  the "you can't compute the signature without doing the walk"
  chicken/egg problem. The first call always misses (warm-load);
  every subsequent call within TTL hits.
- **Sized the TTL deliberately at 60s.** Long enough to swallow
  bursty UI polls; short enough that a freshly-added project
  surfaces "soon-ish" without a manual refresh. Locked into a
  test so a future bump needs deliberate intent.

## What to change / next

- **`/api/projects` cache doesn't catch sibling-add within TTL.**
  Adding a new dir under the configured glob doesn't change any
  *previously-discovered* dir's mtime, so the cache won't see it
  until TTL expiry. Acceptable for the dashboard use case (60s
  delay on first appearance) but worth surfacing in operator docs
  if anyone notices.
- **Language detection is via manifest only.** A repo with no
  manifest gets `unknown` and no badge — accurate but slightly sad.
  Consider adding GitHub `linguist`-style heuristics in a future
  sprint if the unknown rate is high in practice.

## Action items for the next sprint (v7.0.0 GA)

1. **Tag v7.0.0 GA + cumulative retro.** Summarize the 6 alphas,
   write a v8 candidate list extracted from this + previous retros.

## Out-of-scope (still)

- Cross-process projects cache — the UI and MCP each hold their
  own. Not worth adding shared state for the perf gain we'd see.
- Visual regression for the badge colors — covered by the
  Python/JS lockstep test, no need to verify pixel-perfect.

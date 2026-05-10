# Sprint Retro — Harbormaster v16.0.0a1

**Date:** 2026-05-10
**Theme:** Internal quality cluster — three small refactors that
collapse repeated patterns into shared helpers without changing any
observable behaviour.

## What shipped

- **Per-test `network_log` isolation in `tests/conftest.py`**
  (carry-over #2). The ad-hoc autouse fixture from
  `tests/ui/test_network_event_filtering.py` is promoted to a
  session-wide `_reset_network_log` fixture that truncates the
  singleton's `mcp_calls` table around every test. Lazy import keeps
  the optional UI extra non-required.
- **`cachedGetter(host, name, opts, compute)` Alpine helper**
  (carry-over #3). New `_partials/_cached_getter.html` partial
  defines a `window.cachedGetter` global that supports both
  patterns from the v11/v15 surfaces:
  - **deps-only invalidation** (v11.0.0a6 `chatOrder()`)
  - **deps + ttlMs invalidation** (v15.0.0a3 `timelineBuckets`)

  Both call sites in `network.html` migrated. The previous private
  cache slots (`_chatOrderCache`, `_chatOrderEventsLen`,
  `_timelineCache*`) were removed; the helper owns all per-getter
  cache state on `host._gc[name]`.
- **`_make_parser(html: bool)` helper in `markdown.py`**
  (carry-over #7). Both module-level singletons (`_md` strict,
  `_md_html` non-strict) now construct via the shared helper.
  Identical parser configuration except for the `html` flag.

## Numbers

- **Tests**: 1522 → 1535 (+13 net new)
- **Source files**: 57 (unchanged — three extensions only;
  `_partials/_cached_getter.html` is a template, not a Python
  source file)
- **Wall-clock**: ~25 min
- **Commits on main**: 1 feature merge
- **Lint / type**: ruff clean, `mypy --strict` clean
- **Backwards-incompatible changes**: 0
  - `render_safe(text)` signature unchanged; both rendered outputs
    byte-identical for the same input.
  - The Alpine-side getters return the same shape as before; only
    the cache-management plumbing moved.
- **Confirmation: did NOT touch `.github/workflows/*`** — yes.

## What worked

- **Mirror, don't invent.** The shared `cachedGetter` API was
  designed to subsume both the v11.0.0a6 deps-only and v15.0.0a3
  deps+ttl patterns by inspection — the deps tuple grew from one
  element to three (`timelineWindow`, `events.length`,
  `_timelineTick`); a `ttlMs: 0` default keeps the deps-only
  callers ttl-free.
- **Pin tests caught the migration.** `test_caches_phase6.py` and
  `test_v15_live_refresh_polish.py` both pin the cache shape; both
  were updated in the same commit. Without those pins, the
  migration could have silently broken cache invalidation.
- **CWD discipline held.** Worktree CWD persisted across all Bash
  calls in this phase (CWD is auto-set by harness; no `cd` calls
  needed). Discipline lapses for v16.a1: **0**.

## What to change for the next phase

- Continue with carry-overs #4 (pre-commit dev extra), #5
  (suggested-edit doc parity), #12 (auto pre-commit install) for
  v16.a2 — all three are pre-commit-adjacent and combine cleanly.
- Watch for the same "pin test prevented silent regression"
  pattern in v16.a4 (cross-host diff HTML format) and v16.a6
  (waterfall viz) — both are the kind of UI shape change that
  benefits from explicit-shape pins.

## Notes for v16.a6 split decision

Backend instrumentation (the risky part) hasn't started yet.
Decision deferred to a6 itself.

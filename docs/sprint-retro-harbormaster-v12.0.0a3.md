# Sprint Retro — Harbormaster v12.0.0a3

**Theme:** Operator-configurable retention caps. v11 hard-coded
several retention thresholds inside the storage layer (5000 network
log rows, 20 memory revisions per file). Large or quiet deployments
have different needs; v12.0.0a3 surfaces these as a single
`[retention]` config section without changing default behaviour.

## What shipped

### `[retention]` config (`src/harbormaster/config.py`)

New `RetentionConfig` Pydantic model:

```toml
[retention]
network_log_max_rows = 5000        # was hard-coded
memory_revisions_per_file = 20     # was hard-coded
qa_log_recent_k = 100              # optional override of [history]
qa_log_top_recalled_r = 50         # optional override of [history]
```

- Defaults match the v11 hard-coded values exactly — operators with
  no `[retention]` section see identical behaviour.
- `qa_log_*` default to `None` (fall through to `[history]` values).
- Pydantic `Field(gt=0)` gates everything (zero / negative rejected).
- Wired into `HarbormasterConfig` as `retention: RetentionConfig`.

### Store-side instance methods

- `NetworkStore.set_max_rows(n)`: updates `_max_rows` and prunes
  immediately under the existing lock so a tightened cap takes
  effect on the very next `recent()` call instead of waiting for
  the next PRUNE_EVERY-th insert.
- `MemoryRevisionsStore.set_max_per_file(n)`: same shape, but
  iterates every distinct `(project, file)` tuple and prunes each
  independently. Loosening (higher cap) is also safe — the prune
  query is a no-op when row count is below the cap.
- Both methods raise `ValueError` for `n <= 0` (defence-in-depth
  beyond the Pydantic gate).

### Wiring

- `create_app()` calls `network_log.set_max_rows(...)` and
  `memory_revisions.set_max_per_file(...)` after the singletons are
  imported. No-op when defaults are unchanged.
- `tools/_helpers._maybe_record_qa.prune` now consults
  `config.retention.qa_log_recent_k` / `qa_log_top_recalled_r` first;
  falls through to `config.history.retain_recent_k` /
  `retain_top_recalled_r` when the operator hasn't overridden.

## Tests

| Suite delta                                | Before | After |
|--------------------------------------------|-------:|------:|
| Total tests                                | 1240   | 1254  |
| New (`tests/ui/test_retention_config.py`)  | —      |   +14 |

Coverage:

- `RetentionConfig` defaults match v11 hard-coded values verbatim.
- Validation: zero / negative caps rejected by Pydantic.
- `HarbormasterConfig` includes a default `RetentionConfig`.
- `NetworkStore.set_max_rows`:
  - Lower cap → prunes immediately, newest rows preserved.
  - Higher cap → no rows touched.
  - `set_max_rows(0)` and `(-1)` raise ValueError.
- `MemoryRevisionsStore.set_max_per_file`:
  - Lower cap → prunes immediately for the affected tuple.
  - Per-tuple isolation (alpha and beta both pruned independently).
  - Higher cap → no rows touched.
  - `set_max_per_file(0)` raises ValueError.
- `create_app` wiring smoke test: monkeypatch the singletons,
  construct app with `retention=RetentionConfig(network_log_max_rows=42,
  memory_revisions_per_file=7)`, assert both singletons were
  reconfigured. And the no-config path preserves v11 defaults.
- `_maybe_record_qa.prune` source contains both the [retention]
  override branch and the [history] fallback branch.

## Quality gates

```
mypy --strict src/harbormaster   →  Success: no issues found in 56 source files
ruff check src tests              →  All checks passed!
pytest -q                         →  1254 passed, 2 skipped in 39.11s
```

## Architecture notes

- **Why instance methods instead of recreating the singletons?**
  The stores are module-level singletons constructed at import time.
  Replacing them at startup would invalidate every closure / `from`
  import. A `set_max_*` method that updates state in place is
  reversible, testable, and avoids surprising global rebinding.
- **Why immediate prune instead of "next-insert"?** A common
  operational scenario: bump the cap *down* to free up disk space.
  Waiting for the next 100 inserts to shrink the table is the wrong
  default — operators expect "set lower → table shrinks now".
- **Why thread on `[history]` for qa_log?** Two reasons:
  1. The existing `retain_recent_k` / `retain_top_recalled_r` keys
     are deeply baked into the QA history docs; renaming would be a
     breaking change.
  2. Some operators conceptualise QA log retention as part of the
     history config block (it controls behaviour of the
     fastembed-indexed corpus). Surfacing the same knobs in
     `[retention]` is additive — both work.
- **Why iterate distinct tuples for memory_revisions?** The
  `_prune_locked` query is per-(project, file). With one operator
  but many projects we may have 50+ tuples; doing one DELETE per
  tuple is O(N tuples × log rows) which beats a single
  hand-rolled cross-tuple DELETE.

## Deviations

None. Phase scope matched plan exactly.

## Next

Phase 4 — memory revision diff endpoint + extended bleach allowlist.

# Sprint Retro — Harbormaster v22.0.1

**Date:** 2026-05-12
**Theme:** Patch. `delegate_task` now accepts a per-call ``max_turns``
parameter; the previous hardcoded 10 was too low for non-trivial
write delegations and surfaced as the silent
``claude -p exit 1 (no stderr)`` failure that ``max_turns_reached``
produces.

## Triggering incident

First production async delegation post-v22.0.0 GA was a Laravel
feature-parity task for `barsy/collector3.0`:

- Branch `feat/license-pay-assets-package-selection` created ✓
- ResourcePackage model creation, relation wiring, Livewire component
  edits, view changes, translations, tests, commit — **none of the 10
  TODO steps shipped**.
- Job d_855b3149d9d3 failed after 71.5 s with cid 2d54065e and error
  `claude -p exit 1: (no stderr)`.

The session JSONL (`~/.claude/projects/-Users-katsarov-htdocs-barsy-collector3-0/498c886c-...jsonl`)
showed the actual cause:

```json
"attachment":{"type":"max_turns_reached","maxTurns":10,"turnCount":11}
```

claude burned 11 turns just exploring the codebase (step 1 of the
TODO list) before exiting. The 10-turn hardcoded budget made the
async-writes path effectively unusable for any real feature work.

## What landed

| File | Change |
|---|---|
| `src/harbormaster/jobs/schema.py` | DDL gains `max_turns INTEGER NOT NULL DEFAULT 10`; new `MIGRATIONS` list for idempotent ADD COLUMN |
| `src/harbormaster/jobs/store.py` | `Job` dataclass + `enqueue` + `_row_to_job` + `as_dict` carry `max_turns`; `_apply_migrations` runs on open |
| `src/harbormaster/jobs/worker.py` | passes `job.max_turns` to `run_backend` instead of hardcoded 10 |
| `src/harbormaster/tools/delegate.py` | `delegate_task` gains `max_turns: int = 10` parameter; sync + async paths both honour it |
| `tests/unit/test_jobs_store.py` | +2 tests (round-trip persist + legacy-DB migration) |
| `tests/unit/test_jobs_worker.py` | +1 test (worker reads `job.max_turns`) |
| `tests/unit/test_tools.py` | +1 test (sync path delegates per-call max_turns) |
| `src/harbormaster/__init__.py` | 22.0.0 → 22.0.1 |

## Numbers

- 8 files (1 new — this retro). ~110 LOC.
- 1977 → 1981 tests (+4). mypy --strict clean. ruff src/ tests/ clean.

## Lessons

### Silent claude exits mean check the session JSONL

`claude -p` writes a "last-prompt + max_turns_reached" attachment to
its session JSONL when it bumps the turn cap, then exits 1 with no
stderr. Harbormaster's `subprocess.run` captures stderr but the
attachment never goes there. For any future
`code=exit_nonzero: claude -p exit 1: (no stderr)` mystery, the
session JSONL at
`~/.claude/projects/-<encoded-path>/<session>.jsonl` is the
authoritative trace.

Pattern carried forward: when an async delegate fails with no
stderr and the duration is much less than `timeout_local`, suspect
`max_turns_reached` before tuning timeouts.

### Hardcoded internal limits become product surface fast

The v22.0.0a2 worker borrowed `max_turns=10` straight from the v1
sync path's behaviour for `delegate_task`. That was fine while
`delegate_task` was read-only — 10 turns is enough to read a few
files and produce a markdown report. Once writes shipped in
v22.0.0a1, the same 10 became a hard ceiling on what the async
path could actually accomplish.

**Rule:** when a feature flips read-only ↔ writes, audit every
hardcoded budget on the path — turn counts, output caps, prompt
suffixes, timeouts. Each was sized for the old shape.

### Idempotent ADD COLUMN via PRAGMA table_info (carried over from v21.0.8)

`network_log.db`'s v21.0.8 `question_full` column add taught the
pattern: PRAGMA table_info names existing columns; ALTER TABLE ADD
the missing ones with simple defaults. Schema-only migrations are
the only shape supported — anything needing a data backfill belongs
in an explicit one-shot helper.

Migration runs in `JobStore.__init__` after `CREATE TABLE IF NOT
EXISTS SCHEMA`. After that, `_row_to_job` can assume every column
is present and stop branching on column existence (which the v22.0.1
first sketch wrongly did, flagged by ruff SIM118).

## Operator-facing note

After upgrading to v22.0.1:

- Existing callers (`delegate_task(...)` with no `max_turns` arg) keep
  the historical 10-turn cap — same shape as v22.0.0.
- For non-trivial writes, pass `max_turns` explicitly. Empirical
  guideline:
  - Read-only Q&A: 5-10 turns.
  - Single-file edit + commit: 15-25.
  - Multi-file feature with tests: 50-80.
  - Refactor across packages: 100+.
- The cap interacts with `[backends.claude] timeout_local`. With
  ~10 s per turn average, `max_turns=50` typically needs
  `timeout_local ≥ 500`. The default 60 s timeout is short for
  multi-turn writes — bump in TOML before calling.

Upgrade-in-place: the JobStore schema gains a `max_turns` column
automatically on first open after upgrade. Existing rows backfill
to 10. No manual migration step.

# Sprint Retro — Harbormaster v11.0.0a2

**Theme:** Per-file memory revision history.

Closes the v10.0.0a6 risk note: memory edits were destructive, so a
mistaken save could lose information that the operator wanted back.
v11.0.0a2 adds an opt-out-free rolling history of the last 20
revisions per `(project, file)` pair.

## What shipped

- `src/harbormaster/ui/memory_revisions.py` — new module.
  `MemoryRevisionsStore` wraps SQLite at
  `~/.harbormaster/memory_revisions.db` (mode 0600, WAL journal).
  Per-(project, file) cap of 20 revisions, pruned synchronously on
  every insert.
- `MemoryRevision` dataclass: `id, project, file, saved_at,
  bytes_diff, content`. `content` is populated only via the explicit
  `get_revision()` fetch — `history()` returns metadata only to keep
  the listing endpoint cheap.
- `bytes_diff`: signed delta in encoded byte-length vs the previous
  revision; `None` on the first ever revision for a file.
- `src/harbormaster/ui/routes.py`:
  - PUT `/api/projects/{name}/memories/{file_token:path}` now appends
    a revision row after a successful atomic write.
  - POST `/api/projects/{name}/memories` does the same on create.
  - NEW `GET /api/projects/{name}/memory-history?file=<token>` —
    metadata-only revision list, newest first.
  - NEW `GET /api/projects/{name}/memory-revisions/{rev_id}?file=<token>` —
    text/markdown content of the specific revision; 404 unknown.
- `src/harbormaster/ui/templates/project_detail.html` — memory
  editor toolbar gains a "History" toggle. The history aside lists
  revisions newest-first with human-readable timestamps and
  `bytes_diff` badges; clicking a revision opens a read-only preview
  pane with a copy-to-clipboard button.
- `tests/conftest.py` — second env override
  (`HARBORMASTER_MEMORY_REVISIONS_DB`) so the test suite never
  writes to the user's real revisions DB.

## Tests

| Suite delta                       | Before | After |
|-----------------------------------|-------:|------:|
| Total tests                       | 1116   | 1135  |
| New (test_memory_revisions.py)    | —      |   +19 |

Coverage:
- store record / history / get_revision / clear / persist / 0600
- prune cap (default 20, custom 3)
- per-(project, file) isolation
- bytes_diff: None on first, signed delta thereafter
- on-disk schema matches v11.0.0a2 spec
- PUT endpoint records a revision (and the persisted content matches)
- POST endpoint records a revision
- history endpoint returns descending list without `content`
- revision endpoint returns content as text/markdown
- 404 on unknown id, 400 on missing `?file=`
- template integration: toolbar button + alpine factory references

## Quality gates

```
mypy --strict src/harbormaster   →  Success: no issues found in 55 source files
ruff check src tests              →  All checks passed!
pytest -q                         →  1135 passed, 2 skipped in 37.82s
```

## Architecture notes

- URL design — `?file=<token>` query param vs nesting under
  `/memories/{file}/history`. The latter would have collided with
  the existing `{file_token:path}` catch-all viewer route. Query
  params keep the path tree unambiguous.
- `content` deliberately excluded from the history listing — keeps
  the metadata response small even when revisions accumulate.
- Pruning is synchronous, not opportunistic (unlike network_log).
  The per-file cap is small (20) so the DELETE is cheap even on hot
  paths. This is also better UX: a 21st write should not transiently
  show 21 revisions in the panel.

## Deviations

- None. Spec held cleanly.

## Next

Phase 3 — bleach-sanitised memory rendering + live markdown preview
(combined security + UX phase, both touch the markdown rendering
pipeline).

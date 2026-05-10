# Sprint Retro — Harbormaster v14.0.0a5

**Date:** 2026-05-10
**Theme:** Two memory-editor polish items — frontmatter tag pills with
filter input, plus Cmd+Z undo/redo through the v11.a2 revision history.

## What landed

### `harbormaster` (this repo)

| SHA | Subject |
|-----|---------|
| `c7b8a42` | feat(v14.0.0a5): memory tagging UI + Cmd+Z revision undo/redo |

## Capabilities (this sprint)

### 1 · Memory file tagging via YAML frontmatter

The `/api/projects/{name}/memories` listing endpoint now returns a
`tags` array per file alongside `name` / `size` / `mtime`. Tags come
from the file's optional YAML frontmatter:

```markdown
---
tags: [arch, ddd, glossary]
---

# This memory's body
```

The parser is intentionally minimal — no PyYAML dep:

* Reads only the first 4 KiB of the file (frontmatter is at the top).
* Requires the file to start with `---`, find a closing `---` line,
  and contain a single line of the form `tags: [a, b, "c"]`.
* Quoted (single or double) and bare strings both work.
* Anything else returns `[]` silently — never blocks the listing.

The project-detail UI gains a **tag filter input** above the memory
file list. Substring + case-insensitive match against any tag in
`f.tags` filters the visible list. Each list item also renders pill
badges for every tag — the same cyan-on-cyan-bg styling the existing
state-badge helper uses, kept consistent.

### 2 · Undo / redo via revision history (Cmd+Z / Cmd+Shift+Z)

The memory editor's textarea now binds:

* `Cmd+Z` / `Ctrl+Z` → previous (older) revision
* `Cmd+Shift+Z` / `Ctrl+Shift+Z` → next (newer) revision, ultimately
  back to the live on-disk content

Implementation cycle (the cursor is `null` when showing the live
on-disk text, otherwise `0..N-1` indexing the newest-first
`revisions` array):

```
null → 0 → 1 → 2 → ...     (Cmd+Z, going older)
... → 1 → 0 → null         (Cmd+Shift+Z, going newer)
```

When `Cmd+Shift+Z` lands at `null`, the editor re-fetches the live
file content (so a concurrent external edit isn't masked). Cursor
resets to `null` whenever the user `select()`s a different file.

Saves continue to create new revisions exactly as in v11.a2 — undo
traversal is purely read-only.

A small status line below the textarea (`position: #2 of 8` or
`position: live`) only appears while editing AND when at least one
prior revision exists, so the UI doesn't shout at users on a fresh
file.

## Real numbers

- 2/2 v14.a4 sprint-plan items shipped (tagging + undo/redo)
- 1 commit, 3 files changed (1 server module, 1 template, 1 test)
- 13 new tests in `test_v14_memory_tags_and_undo.py`:
  - frontmatter parser: 6 cases (basic / no FM / quoted / malformed /
    serena subdir / 4 KiB cap)
  - UI wiring: 7 cases (filter input, pill loop, empty-filter
    early return, four keybinds, cursor null init, status-line gate)
- Test suite delta: 1398 → 1411 passed
- Lint: ruff clean. Type-check: `mypy --strict` clean (57 source files)
- Backwards-incompatible changes: 0 (`tags` field additive on the
  listing endpoint; new keybinds intercept Cmd+Z but only inside
  the editor textarea)

## What worked

- **Bounded-cost frontmatter parse.** Capping the read at 4 KiB
  means a memory file with a multi-MB body still costs the same
  to inspect — the listing endpoint stays cheap regardless of
  per-file size.
- **Reusing the existing `revisions` array for undo state.** No
  separate undo stack means no "is the undo state stale relative
  to revisions?" worry. The cursor is just an index.
- **Status line gated on `editing && revisions.length > 0`.** Same
  pattern as `x-show="diffOutput || diffError"` from v12.a4 — keeps
  empty states from cluttering first-load.

## What to change / next

- **Cmd+Z hijacks the OS-native textarea undo stack.** A user who
  expected undo to revert the last keystroke gets a revision-load
  instead. Acceptable trade-off for memory editing (revisions are
  saved on `save()`, not per keystroke), but worth a docstring
  comment on the keybind explaining the override.
- **Tag parser doesn't handle YAML block lists** (`tags:\n  - foo\n  - bar`).
  Only the inline `tags: [a, b]` form. If real operator content
  uses block lists we'd need a small extension; for now the docs
  + commit message implicitly require inline form.

## Action items for the next sprint (v14.0.0a6)

1. **Plugin discovery cross-host.** Currently `[plugins]` config +
   entry-point discovery is local only. Extend `harbormaster.plugins`
   to query remote hosts via SSH (mirror of remote-host queries in
   `backends/claude.py`). New endpoint
   `GET /api/plugins?host=<name>` returns remote plugin discovery
   results. UI: status strip plugin card adds host filter (default:
   local).

## Out-of-scope (still)

- Multi-tag intersection / union filtering (only single-substring
  match in v14.a5; multi-input would need a tag-chip UI).
- YAML block-list tag form (covered above).
- Persisting cursor position across page reloads — undo through a
  refresh isn't a strong UX requirement.

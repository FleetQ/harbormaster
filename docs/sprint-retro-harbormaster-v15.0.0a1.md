# Sprint Retro — Harbormaster v15.0.0a1

**Date:** 2026-05-10
**Theme:** Memory tag UX cluster — three v14-retro carry-overs combined.

## What shipped

- **YAML block-list tag form** (#2): server-side `_extract_memory_tags`
  now also accepts the canonical `tags:\n  - foo\n  - bar` shape
  alongside the existing inline list form. Stops at the next non-list
  / different-key line.
- **Multi-tag intersection / union filter** (#3): the tag filter input
  comma-splits its tokens; an AND/OR pill toggle controls match mode.
  AND (default) requires every token to substring-match a tag; OR
  requires at least one. Empty filter = identity (unchanged).
- **Persist undo/redo cursor across page reloads** (#4): the
  `revisionCursor` value is written to `localStorage` keyed by
  `hm:revcursor:<project>:<file>`. On `select()` the cursor is
  restored from storage (replacing the v14 reset-to-null behaviour);
  switching to a different file picks up that file's own cursor.
  Cursor=null clears the storage entry.
- **Chip-input tag editor** (UX delivery for #2): when editing a memory,
  the YAML-frontmatter tags render as removable chips with an
  "add tag" input. Mutations rewrite the draft frontmatter as a YAML
  block-list (round-trips with the parser). The textarea remains
  available; chips re-derive from frontmatter on every `startEdit()`.

## Numbers

- **Tests**: 1429 → 1442 (+13)
- **Source files**: 57 (no change — pure UI + parser extension)
- **Wall-clock**: ~30 min
- **Commits on main**: 1 feature merge (`Merge feat/v15.0-memory-tag-ux`)
- **Lint / type**: ruff clean, `mypy --strict` clean
- **Backwards-incompatible changes**: 0 (one v14 test internal-assertion
  updated for the new filter shape; public behaviour preserved)

## What worked

- **Symbol-first exploration via Serena.** `find_symbol("_extract_memory_tags")`
  with `include_body=true` cut straight to the parser without
  reading routes.py (2681 lines). Same for the Alpine state block —
  `search_for_pattern` against the template located the four
  insertion points in <2s.
- **Backwards-compatible parser extension.** The block-list path is
  gated on `value == ''` after the inline-form check, so existing
  inline-list memories keep working byte-for-byte. v14's six tag-parser
  tests still pass as-is.
- **localStorage as the cursor store.** `_persistCursor` /
  `_restoreCursor` helpers wrap the try/catch boilerplate so the
  call sites stay one-liners. Storage failures are silent (operator
  may have it disabled — falls back to live).

## What to change

- **`cd <worktree>` discipline.** First commit landed in the parent
  main checkout instead of the feat branch because the cwd reset
  between Bash calls drops you back to wherever the env says you're
  rooted. CRITICAL lesson #1 exists for a reason — recovered via
  cherry-pick + reset of unpushed main, but cost ~5 minutes of
  detective work. Going forward, every Bash call starts with
  `cd "/Users/katsarov/htdocs/harbormaster/.claude/worktrees/<id>"`.
- **No `.venv` in worktrees.** Worktrees share the parent's git
  but not its `.venv`. Use `/Users/katsarov/htdocs/harbormaster/.venv/bin/<tool>`
  with the absolute path, not the relative `.venv/bin/<tool>` path.

## Next phase (v15.0.0a2)

- Concurrent multi-host plugin discovery via `?host=all` + `asyncio.gather`
- Cross-host config diff via `query_remote_config` + `/api/config/diff`

## Halt assessment

- 11 candidates remain; v15.0.0a1 closes 3 of the 12 v14-retro items.
- Test suite green, lint clean, no breaking changes — release bar met.
- **Continue.**

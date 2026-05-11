# Sprint Retro — harbormaster v19.0.0a8

**Phase 6 of v19.0** — full Memories tab implementation. Closes the
operator's "v10 over-reported memories editor" gripe.

> **Versioning note** — Phase 6 was originally specced to ship as
> `v19.0.0a6`, parallel with Phase 5 (`v19.0.0a5`). During Phase 6
> work, an unscheduled Phase 7 (SSE-driven inspector activity feed)
> jumped onto main and claimed both `v19.0.0a6` and `v19.0.0a7`
> consecutively. To preserve semver monotonicity we shipped this work
> as `v19.0.0a8`. Lessons captured in §Friction.

## What shipped

A split-pane Memories editor that replaces both the v19.a2 placeholder
banner and the legacy v10..v15 `memoriesPanel` viewer. The new layout:

- **LEFT pane** — file list with size + tag pills + a `+ new` button.
  Auto-selects the first file on load.
- **RIGHT pane** — textarea bound to `content` + a live markdown
  preview (300 ms debounced POST to `/api/render-markdown`). Cmd/Ctrl+Z
  bindings drive a local undo/redo history stack (no server roundtrip
  per keystroke).
- **Toolbar** — Save (gated on `dirty`), Undo / Redo (gated on the
  computed `canUndo` / `canRedo` flags), and a "diff vs:" dropdown
  that fetches the v13.a3 sanitised HtmlDiff table on demand.
- **Diff panel** — collapses when `diffAgainst` is empty; expands
  inline below the editor when a revision is selected.
- **New file flow** — `window.prompt` for the filename + POST to
  `/api/projects/{name}/memories` with the standard allowlist
  (`CLAUDE.md` or `.serena/memories/<name>.md`).

The legacy `memoriesPanel` block (≈850 lines of template + Alpine
factory) is wrapped in `{% if false %}` so Jinja never emits it.
Marked with `data-legacy-removed="memoriesPanel-v15"` so a follow-up
release can nuke it cleanly once the new editor has soaked.

## Backend contract reused

Zero new endpoints. Everything piggybacks on the existing API surface:

- `GET /api/projects/{name}/memories` — file list (with sizes + tags).
- `GET /api/projects/{name}/memories/{file_token:path}` — raw text.
- `PUT /api/projects/{name}/memories/{file_token:path}` — atomic save
  (with revision recording).
- `POST /api/projects/{name}/memories` — create new file.
- `GET /api/projects/{name}/memory-history?file=…` — revision metadata
  (id, saved_at, bytes_diff).
- `GET /api/projects/{name}/memory-revisions/diff?file=…&from=…&format=html`
  — sanitised HtmlDiff table.
- `POST /api/render-markdown` — `{text, project}` → bleach-safe HTML.

## Tests

- **New** — `tests/ui/test_v19_memories_tab.py` (12 template-source
  assertions covering placeholder removal, legacy-block inertness,
  factory mounting, file list, split editor, toolbar wiring, diff
  panel, factory contract, render-markdown body shape, history
  endpoint query string, diff format, and tabpanel role preservation).
- **Updated** — `tests/ui/test_v19_project_tabs.py`: drop the memories
  placeholder parametric case (Memories no longer ships a banner).
- **Updated** — `tests/ui/test_markdown_render.py`: switch the live-
  preview assertions to the new editor's labels (`Live markdown
  preview`, `renderPreview`).
- **Updated** — `tests/ui/test_memory_revisions.py`: switch the
  revision-history assertions to the new editor's contract
  (`loadRevisions`, `aria-label="Diff against revision"` dropdown).
- **Updated** — `tests/ui/test_revision_diff_and_bleach.py`: rename
  `diffFrom` → `diffAgainst` and accept the new query-string ordering
  (`?file=…&from=…&format=html`).

Test count: **1719** (a4 baseline) **+ 12** (new memories-tab tests)
**= 1731** before deduping shared fixtures, **1731** in the final
`pytest -q` run on this branch.

## Gripe closed

> "v10 over-reported memories editor"

The v10.0.0a5 → v15.0.0a1 stack accumulated five releases worth of
features inside a single read-mode-with-toggle-edit panel that always
felt half-finished — the toolbar moved, the chip editor and the tag
filter competed for space, the history panel collapsed/expanded
independently of the diff dropdown, and the operator could never see
the markdown source and rendered output at the same time. The
v19.0.0a6 split pane gives a fixed layout: text on the left, render on
the right, history-as-diff in a dropdown. No mode toggling. No hidden
state.

## Lessons / friction

1. **Verifier server caches templates at startup.** Restarting the
   `harbormaster-ui` process is required after any template edit
   before screenshots will reflect the change. The first verification
   pass showed an old-style Memories tab because the verifier was
   started before the `Edit` calls landed.
2. **Parallel-branch concurrency on a shared working tree.** Phase 7
   (SSE activity feed, also v19.0.0a7) ran in the same checkout
   simultaneously. Two times during Phase 6 the working tree got
   switched to the other branch out from under us, and the
   `dashboard.html` modifications from Phase 7 leaked into our
   `git status`. **Fix**: always use `git worktree add` for parallel
   branch work — Phase 6 finished cleanly only after moving to a
   `/tmp/hm-memories-editor` worktree. CLAUDE.md already mandates this
   for any agent that does git mutations; the spec for parallel-phase
   sprints needs to enforce `isolation: "worktree"` on every phase, not
   just the ones flagged risky.
3. **Semver collisions when phases race.** Spec said "ship a6", but
   Phase 7 raced ahead and claimed both a6 and a7 sequentially. We
   shipped as a8. **Fix**: the sprint orchestrator should hand each
   phase a guaranteed-unique alpha number at dispatch time, not at
   ship time, OR each phase should bump to "next-available" via a
   `git ls-remote --tags` lookup right before tagging.
3. **`/api/render-markdown` body shape mismatch.** The endpoint
   accepts `{text: …}` (with optional `project: …`), NOT `{content: …}`
   (which is the PUT memories body). Test
   `test_render_markdown_post_uses_text_field` pins this so the next
   editor doesn't drift.
4. **`memory-revisions/diff` query order is irrelevant.** FastAPI
   parses `?file=…&from=…&format=html` the same as `?from=…&file=…&format=html`,
   so we standardised on the file-first ordering for readability.

## What's left for v19.0 GA

The five-tab structure (Overview, Memories, Trajectories, Q&A History,
Settings) is now anchored:
- a1 — three-column shell foundation
- a2 — project tabs
- a3 — context-aware inspector pane
- a4 — Linear violet tokens + compact density
- a5 — dashboard relayout
- a6 — (claimed by Phase 7's first bump; effectively skipped for
       Memories editor)
- a7 — SSE-driven inspector activity feed (Phase 7)
- **a8 — Memories editor (this release, Phase 6 deliverable)**
- TBD — Q&A History project-scoped recall (target: next available alpha)
- TBD — per-project budget editor (target: alpha after that)
- v19.0.0 GA — polish + screenshot-diff baselines

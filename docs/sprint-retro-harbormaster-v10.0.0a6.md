# Harbormaster v10.0.0a6 — Sprint Retro

**Phase 6 of 8** in the v10.0 alpha chain.

## Shipped

**Per-project memories editor (atomic write-back).**

Builds on v10.0.0a5's read-only viewer: operators can now edit
`CLAUDE.md` and `.serena/memories/*.md` directly in the browser
with PUT/POST endpoints and a textarea editor.

## Implementation

Server (`ui/routes.py`):
- `PUT /api/projects/{name}/memories/{file_token:path}` — upserts
  the file (creates if missing). Body = `{content: <str>}`.
  Returns `{file, size, mtime, created}`.
- `POST /api/projects/{name}/memories` — creates a new file in
  the allowlist. Returns 409 if the target already exists.
- New `_atomic_write()` helper: writes to `<target>.hm-tmp`, then
  `Path.replace()` for atomic swap; mode 0o644; cleans up the
  temp file on any failure path. Auto-mkdirs `.serena/memories/`
  when needed.
- Same allowlist + traversal protections as a5's GET path.
  Containment check accommodates create-by-PUT (anchor switches to
  `target.parent` when target doesn't exist yet).
- Pydantic body models forbid extra keys.

UI (`templates/project_detail.html`):
- New edit toolbar above the rendered article: Edit/Cancel/Save.
- `<textarea>` becomes the editor when in edit mode; markdown
  re-renders on save via the vendored marked.js.
- New collapsible `<details>` form for creating a new memory file:
  filename + content textarea + Create button.
- All buttons carry `aria-label` so the icon-only-button audit
  accepts them.

## Tests (11)

`tests/ui/test_memories_editor.py`:
- PUT updates an existing CLAUDE.md.
- PUT creates when target missing (upsert semantics).
- POST creates a serena memory (auto-mkdirs `.serena/memories/`).
- POST creates CLAUDE.md.
- POST returns 409 when target already exists.
- PUT path traversal `..%2F` → 400.
- POST disallowed filename → 400.
- POST mkdirs missing serena dir.
- PUT unknown project → 404.
- PUT cleans up `.hm-tmp` after success.
- Template wires `startEdit` / `save` / `createNew` handlers.

## Numbers

- Tests: 1064 → 1075 (+11).
- Source files: 52 → 52 (no new modules).
- mypy --strict: clean.
- ruff: clean.

## Deviations

- The plan said "atomic write (temp file + rename); preserve file
  mode (0644 default)". Implemented as specced — `chmod 0o644` is
  a best-effort post-rename step (silently swallowed on platforms
  where chmod fails, e.g. tmpfs without permission bits).
- The plan implied PUT is update-only; chose upsert (PUT-create
  when target missing) for symmetry with REST norms and to support
  bookmark-style editing of a known filename. POST remains the
  exclusive create path that 409s on conflict.

## Risks / Follow-ups

- No revision history yet — overwriting CLAUDE.md is destructive.
  Future enhancement: keep last-N versions in `<file>.hm-prev` for
  one-click rollback. Out of scope for v10.
- Bearer-token middleware gates this surface, but no per-action
  confirm. Operator decision (locked in
  `harbormaster_autonomous_chain_decisions`): Bearer sufficient.
  Re-visit if shared-tenant use cases emerge.
- The textarea is raw markdown — no preview-while-editing. Live
  preview is a follow-up; the current Edit/Save round-trip is
  fast enough that the friction is small.

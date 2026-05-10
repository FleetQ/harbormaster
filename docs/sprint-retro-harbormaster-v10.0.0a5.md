# Harbormaster v10.0.0a5 — Sprint Retro

**Phase 5 of 8** in the v10.0 alpha chain.

## Shipped

**Per-project memories viewer (read-only).**

The project detail page now lists `CLAUDE.md` and every
`.serena/memories/*.md` for the current project, and renders the
selected file's markdown in-place using a vendored copy of
marked.js.

## Implementation

Server (`ui/routes.py`):
- `GET /api/projects/{name}/memories` — returns
  `{project, files: [{name, size, mtime}]}`. Sorted; non-md files
  in serena are skipped.
- `GET /api/projects/{name}/memories/{file_token:path}` — returns
  the raw markdown body. Allowlist: exact `CLAUDE.md` OR
  `.serena/memories/<basename>.md` where basename matches the same
  strict regex as `validate_project_name`.
- Path traversal locked: rejects `..`, `\`, absolute paths,
  nested-slash basenames. Belt-and-braces post-resolve
  `relative_to(project_root)` containment check defeats symlinks
  pointing outside the project directory.
- 404 on unknown project / missing file. 400 on bad token.

UI (`templates/project_detail.html`):
- New `<section x-data="memoriesPanel(...)">` — file list (left,
  ⅓ width on md+) + rendered article (right, ⅔ width).
- Empty state matches the established 3-part canonical pattern
  (header sentence + descriptor + neutral CTA).
- Renders via `window.marked.parse()`; defensive fallback to
  preformatted text if the vendored script failed to load.
- Each file selector button has a dynamic `:aria-label` so the
  icon-only-button audit (`test_a11y_floor.py`) accepts it.

Vendored asset:
- `src/harbormaster/ui/static/vendor/marked.min.js` — marked
  v12.0.2, MIT, 35KB. Served via the existing `/static/{path}`
  route (which already enforces traversal blocking).

## Tests (13)

`tests/ui/test_memories_viewer.py`:
- Empty list when no files.
- Mixed `CLAUDE.md` + serena listing with size + mtime; non-md
  files in serena are skipped.
- GET `CLAUDE.md` and `.serena/memories/<name>.md` both return raw
  markdown with `text/markdown; charset=utf-8`.
- Unknown project → 404. Missing file → 404.
- Path traversal `..%2F` → 400.
- Disallowed filenames (e.g. `secret.md` at project root) → 400.
- Nested-slash inside basename → 400.
- Template includes the marked vendor script tag and panel scope.
- Vendored marked.min.js is on disk and served via /static/.

## Numbers

- Tests: 1051 → 1064 (+13).
- Source files: 52 → 52 (no new modules; routes added to
  existing `ui/routes.py`).
- mypy --strict: clean.
- ruff: clean.

## Deviations

None. Implemented exactly as specced.

## Risks / Follow-ups

- The endpoint returns raw markdown, so the browser renders it
  via marked.js — XSS risk depends on what's in CLAUDE.md /
  serena memories. These are operator-controlled files (operator
  wrote them or trusts the source); the bearer-token middleware
  also gates access. If we later let public users view memories,
  switch the renderer to bleach-sanitised HTML server-side.
- Phase 6 (memories editor) builds on this surface — same
  allowlist + traversal protection, plus PUT/POST.
- The `marked.min.js` vendor file ships in the wheel via the
  existing hatchling auto-include for `packages = ["src/harbormaster"]`.
  No `force-include` needed.

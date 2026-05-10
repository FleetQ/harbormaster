# Sprint Retro — Harbormaster v11.0.0a3

**Theme:** Bleach-sanitised markdown rendering + live preview pane.

Combined v10's two open risk notes into a single phase: server-side
sanitisation for the memory viewer (a5/a6 was unsanitised) AND a
live-preview UX while editing.

## What shipped

- `src/harbormaster/ui/markdown.py` — new module exposing
  `render_safe(md_text) -> str`. Pipeline:
  - `markdown-it-py` (CommonMark + GFM tables) renders raw HTML.
  - `bleach.clean()` strips disallowed tags / attributes / protocols.
  - Allowlist: standard markdown tag set + `table`/`thead`/`tbody`/
    `tr`/`th`/`td`. Attributes: `href` on `a`, `class` on `code`/
    `pre`, `align` on `th`/`td`, `src`/`alt` on `img`. Protocols:
    `http`, `https`, `mailto` only.
- `src/harbormaster/ui/routes.py`:
  - `GET /api/projects/{name}/memories/{file}?render=html` — returns
    sanitised HTML when the query param is set; raw markdown
    otherwise (preserves v10 contract).
  - `POST /api/render-markdown` — accepts `{"text": "..."}`, returns
    sanitised HTML. Powers the editor's debounced live preview.
- `src/harbormaster/ui/templates/project_detail.html`:
  - Editor became split-pane: textarea on the left, live-preview
    panel on the right. Updates debounce 300ms via
    `@input.debounce.300ms="updatePreview()"`.
  - Viewer-side render now prefers the server-side `?render=html`
    path; falls back to the v10 client-side `marked.js` path on
    failure (older deploys missing the endpoint).
- `pyproject.toml`:
  - `markdown-it-py>=3.0` added to `[ui]` and `[dev]` extras.
  - `[bleach]` mypy override added (no shipped stubs).

## Tests

| Suite delta                       | Before | After |
|-----------------------------------|-------:|------:|
| Total tests                       | 1135   | 1154  |
| New (test_markdown_render.py)     | —      |   +19 |

Coverage:
- Sanitisation: script / style / iframe stripping; onclick attribute
  cannot survive on a live `<a>` (raw HTML escaped to text);
  `javascript:` / `data:` / `vbscript:` URI schemes blocked at the
  link level; `http` / `https` / `mailto` schemes pass.
- Markdown fidelity: headings, emphasis, code, lists, blockquotes,
  fenced code blocks, GFM tables, `language-*` class on `<code>` for
  syntax highlighting hooks.
- Endpoint integration: GET `?render=html` returns text/html with
  the sanitised body; default GET still returns raw markdown.
  POST `/api/render-markdown` works with full / empty / missing text.
- Template integration: live-preview pane present, debounce hint
  present, `updatePreview` factory method wired.

## Quality gates

```
mypy --strict src/harbormaster   →  Success: no issues found in 56 source files
ruff check src tests              →  All checks passed!
pytest -q                         →  1154 passed, 2 skipped in 37.79s
```

## Architecture notes

- markdown-it-py with `html=False` already escapes raw HTML to text
  before bleach gets to it. Belt-and-braces: bleach still runs on
  every render, so even if a future config flip enabled raw HTML in
  the parser, the sanitiser is the trusted boundary.
- markdown-it-py's `validateLink` hook drops dangerous URI schemes
  during parse, so a `[click](javascript:alert(1))` link never even
  becomes an `<a>`. Bleach's protocol allowlist is the second line
  of defense.
- The viewer's fallback to client-side `marked.js` rendering is
  intentional — operators upgrading from v10 with the endpoint not
  yet available shouldn't see a broken rendered pane.

## Deviations

- Spec called for a separate top-level `render_safe` helper that the
  editor could call optionally; we made it the DEFAULT path
  (server-side render via `?render=html`) and kept marked.js as a
  fallback. Result is more consistent: viewer + post-save pane both
  see the same bleach-sanitised output.

## Next

Phase 4 — stateBadge unification + `?q=` URL pre-fill (UX
consistency polish).

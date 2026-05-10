# Sprint Retro — Harbormaster v12.0.0a4

**Theme:** Memory revision diff endpoint + extended bleach allowlist —
two memory-cluster items combined.

## What shipped

### Diff endpoint (`src/harbormaster/ui/routes.py`)

- `GET /api/projects/{name}/memory-revisions/diff
   ?from=<rev_id_a>&to=<rev_id_b>&file=<token>`
- `to=` optional. When omitted: right-hand side is the current
  on-disk file content. The common operator question — "what
  changed since this revision?" — gets a one-arg call.
- Implementation uses stdlib `difflib.unified_diff` (no new deps).
- `Response(media_type="text/plain; charset=utf-8")` — diff text
  drops straight into a `<pre>` element on the client.
- Defence-in-depth: `target.relative_to(cwd.resolve())` rejects
  `?file=../etc/passwd`. Validation order: project name → file
  non-empty → `from` revision exists → `to` revision exists OR
  current file exists & is inside project root.
- Routing: declared BEFORE `/memory-revisions/{rev_id}` so the
  literal `diff` segment binds correctly. (Test enforces this — a
  collision would surface as 422 instead of 404.)

### Bleach allowlist (`src/harbormaster/ui/markdown.py`)

Tags added: `details`, `summary` (collapsible blocks), `sup`, `sub`,
`section` (footnote markup emitted by markdown-it footnote plugins).

Attributes added:
- `a`: `class`, `id` (footnote-ref / footnote-link / fnref-N).
- `li`: `id`, `class` (footnote items).
- `section`: `class` (footnotes wrapper).
- `sup`: `class`.
- `details`: `open`.

Verified that `<script>`, `<iframe>`, and `javascript:` hrefs are
still stripped — the additions don't open a hole.

### UI dropdown (`templates/project_detail.html`)

- "Diff against revision" `<select>` next to the existing History
  toggle button. Visible when the history panel is open AND there's
  at least one revision on file.
- Selecting a revision fires `loadDiff()` which calls the new
  endpoint and renders the unified diff under the revision-preview
  pane.
- Three new state vars: `diffFrom`, `diffOutput`, `diffError`. All
  reset in `toggleHistory()` so closing+reopening the panel is a
  clean slate.

## Tests

| Suite delta                                       | Before | After |
|---------------------------------------------------|-------:|------:|
| Total tests                                       | 1254   | 1269  |
| New (`tests/ui/test_revision_diff_and_bleach.py`) | —      |   +15 |

Coverage:

- Diff endpoint:
  - `?from=A` (no to) → diff against current; `+++ current` label.
  - `?from=A&to=B` → diff between two revisions; both labels appear.
  - 404 for missing `from` or missing `to`.
  - 400 for empty `?file=`.
  - Path-traversal attempt (`?file=../...`) returns 400 OR 404
    (both block the attack).
  - Endpoint vs `{rev_id:int}` collision: literal `diff` binds the
    diff handler (404 not 422).
- Bleach:
  - `<details open>`, `<summary>` survive.
  - Footnote markup classes + ids (footnote-ref, footnote-link,
    fnref-N, footnote-item, footnotes section) survive.
  - `<script>` and `javascript:` hrefs still stripped.
- UI:
  - `diffFrom` state + `loadDiff()` method present in factory.
  - `aria-label="Diff against revision"` present.
  - Endpoint URL built with both `?from=` and `&file=`.
  - `toggleHistory()` resets all three diff state vars.

## Quality gates

```
mypy --strict src/harbormaster   →  Success: no issues found in 56 source files
ruff check src tests              →  All checks passed!
pytest -q                         →  1269 passed, 2 skipped in 39.13s
```

## Architecture notes

- **Why text/plain instead of JSON?** A unified diff is a text
  artefact — line-prefixed `---` / `+++` / `@@` markers carry the
  meaning. Wrapping in JSON adds an extra parse step on the client
  (and forces a `JSON.parse` of an arbitrarily-large string). Plain
  text drops into a `<pre>` directly.
- **Why server-side diff instead of client-side `diff` library?**
  - No new vendored JS dependency.
  - Server already has both texts in memory (revision content + on-
    disk current). One round trip + stdlib call.
  - Operator gets exactly the diff the server computes — no
    client-vs-server output drift.
- **Why two query params (from + to) instead of POST body?**
  Idempotent + cacheable + bookmarkable. Operators sharing diff
  URLs in chat is a real workflow.
- **Why allow `<details>` + `<summary>`?** Operators paste runbook
  / issue-template content into memory files. Collapsed
  troubleshooting steps are a readability win and don't introduce
  any new attack surface — the `open` attribute is the only one
  that affects rendering, and bleach validates it as a known attr.
- **Why route the diff endpoint BEFORE the `{rev_id}` route?**
  FastAPI matches routes in declaration order. `/diff` would
  collide with `/{rev_id:int}` if declared after — FastAPI would
  try `int("diff")`, fail, and return 422. Declaration order is
  load-bearing here; the test pins it.

## Deviations

None. Phase scope matched plan exactly.

## Next

Phase 5 — network stats by-source breakdown + worktree helper script.

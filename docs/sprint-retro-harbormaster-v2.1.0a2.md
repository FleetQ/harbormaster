# Sprint Retro — Harbormaster v2.1.0a2

**Date:** 2026-05-09
**Theme:** Project detail page. Cards on the dashboard get a click
target — `/projects/{name}` rendering git log + Serena memories +
path on a server-rendered Jinja template. Sets up the surface where
v2.1.0a4–a6 will live.

## What landed

| SHA | Subject |
|-----|---------|
| (squash) | feat(ui): project detail page at /projects/{name} (#24) |

## Capabilities

### 1 · `GET /projects/{name}`

Server-side rendered Jinja template. Validates the project name,
400 on invalid (path traversal etc.), 404 on unknown project. Calls
the existing `_local_status` (or `_remote_status` when `?host=` is
set) — same code path as the `project_status` MCP tool — and passes
the markdown string to the template.

### 2 · `project_detail.html`

Three sections:
- Breadcrumb back to dashboard + host indicator chip when `?host=`
- Header card: name + last commit + brief + serena/claude.md badges + path
- Status block: `<pre class="whitespace-pre-wrap">` of the markdown
  string. No client-side markdown parser — the output is human-readable
  as plain text.

Plus a placeholder card pointing forward to v2.1.0a4 (ask form),
v2.1.0a5 (delegate form), v2.1.0a6 (trajectory history) — sets
expectation that this is the live surface.

### 3 · Dashboard cards now navigate

`<article>` wrapped in `<a href="/projects/{name}">`. Hover keeps
the existing border-color transition. No JS event handler needed —
plain anchor tag.

## Real numbers

- 1 PR opened / merged (#24)
- 6 new tests
- Test suite: 530 → **536 pass, 1 skip**
- mypy --strict: 46 source files clean
- ruff: clean
- Backwards-incompatible changes: 0
- Lines changed: +206 / -16

## What worked

- **Server-side render, zero new client JS.** The detail page is pure
  Jinja2 + Tailwind classes. No EventSource bookkeeping, no Alpine
  components — all the work happens on the server, which is appropriate
  for a read-only status page.

- **Reuse `_local_status` / `_remote_status` directly.** Importing
  the helpers from `harbormaster.tools.projects` gives the same output
  as the `project_status` MCP tool — UI and MCP can never drift in
  what status they report.

- **Plain `<pre>` instead of markdown rendering.** The status output
  IS readable as plain text (Markdown is the reading-friendly form).
  Adding `marked.js` would have meant another CDN script tag without
  meaningful UX win for this surface.

## What to change / next

- **No "Next/Previous project" navigation.** A small UX win for users
  who want to skim N projects in a row. Defer; not blocking.
- **No copy-to-clipboard for the path.** Useful since the path is
  exactly what users would paste into `cd`. Defer.
- **Status markdown contains hyphens that break Tailwind's
  `whitespace-pre-wrap` line-wrap.** Fixed by also setting
  `break-words`. Note for future template authors.

## Action items for the next sprint (v2.1.0a3)

1. **Recall search inline on the dashboard.** Text input + Alpine
   submission to `POST /mcp/harbormaster` with `recall_qa(question)`.
   Render hit cards inline. Drives the v1.2 phase 1 history feature
   from the browser.

## Out-of-scope (still)

- Tauri / Electron desktop UI wrapper
- Live FleetQ runtime state in /api/bridge/status
- Markdown rendering on the detail page (Markdown source is human-readable)
- Headless browser tests

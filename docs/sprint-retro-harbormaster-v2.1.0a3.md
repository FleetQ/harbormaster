# Sprint Retro — Harbormaster v2.1.0a3

**Date:** 2026-05-09
**Theme:** Recall search lands on the dashboard. The v1.2 history
store finally has a browser-side surface — search input, project
filter, host selector, match cards. Cross-references project detail
pages so a recall hit becomes one click away from full project status.

## What landed

| SHA | Subject |
|-----|---------|
| (squash) | feat(ui): recall search inline on dashboard (#25) |

## Capabilities

### 1 · `GET /api/recall`

Browser-friendly wrapper around the `recall_qa` MCP tool. Returns
the raw result dict so a `fetch().then(r => r.json())` consumer
skips the MCP content-envelope unwrap.

Query params: `question` (required), `project`, `top_k`,
`min_similarity`, `host`. Honors v2.0.0a6's `host="all"` cross-host
fan-out path verbatim — the endpoint imports the same
`_recall_one_host` helper.

Soft fails: returns `{enabled: false, message: ...}` when
`[history].enabled = false`, when the [history] extra isn't
installed, or when `question` is empty/whitespace-only.

### 2 · Recall section on the dashboard

Above the project graph — high prominence. Form fields:
- text input (required, min 2 chars)
- project filter (optional)
- host selector: `local` / `all hosts`
- submit button (disabled while loading or below min length)

Result list renders match cards with project link →
`/projects/{name}?host={host}`, host badge, tool name, score, the
recorded question, and a 3-line clamp of the answer. Empty-state
messaging when no matches.

### 3 · Recall ↔ project detail integration

The match-card project link uses the v2.1.0a2 detail route
(`/projects/{name}?host=...`) so users can flow from recall hit →
full project status in one click. The host param is preserved when
the match came from a remote store.

## Real numbers

- 1 PR opened / merged (#25)
- 6 new tests in `test_ui.py`
- Test suite: 536 → **542 pass, 1 skip**
- mypy --strict: 46 source files clean
- ruff: clean (one unused-import lint surfaced + fixed before push)
- Backwards-incompatible changes: 0
- Lines changed: +278 / -0

## What worked

- **JSON wrapper over MCP envelope.** `/api/recall` returns the dict
  directly. Saves the browser from doing
  `JSON.parse(response.result.content[0].text)` and keeps client code
  simple. The cost is ~95 lines of routing code that mirrors the MCP
  tool — but the import-recall-helper pattern keeps it from drifting.

- **Cross-link to project detail page.** Each match card's project
  name is an anchor to `/projects/{name}` from v2.1.0a2. The flow
  from "search recall → see project" is now zero friction. This is
  the value proposition the research report called out.

- **Disabled-state messaging.** Three different "off" paths
  (`[history].enabled=false`, missing extra, empty question) all
  surface a one-line `message` field that the dashboard prints in
  amber. Operators see WHY recall returned nothing instead of
  guessing.

## What to change / next

- **No keyboard shortcut to focus the search input.** A `/` global
  binding (GitHub-style) would make repeat searches faster. Defer.
- **No URL state for queries.** Reload loses the search; would be
  nicer if `?q=...&project=...` populated the form on page load.
  Defer; not blocking.
- **No "n results" pagination.** `top_k` is a config default;
  showing more than 5 takes scrolling. The actual store rarely
  exceeds that for narrow questions, so it's fine.

## Action items for the next sprint (v2.1.0a4)

1. **"Ask this project" SSE form.** Inline form on the project
   detail page (and possibly each card on dashboard). EventSource
   consumer streams chunks from the existing
   `POST /mcp/{server}` SSE path. Closes the loop: from "see
   recall hit" to "ask a fresh question of the same project" without
   leaving the browser.

## Out-of-scope (still)

- Tauri / Electron desktop UI wrapper
- URL state encoding for recall queries
- Keyboard shortcuts
- Headless browser tests

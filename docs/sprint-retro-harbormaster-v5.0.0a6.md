# Sprint Retro — Harbormaster v5.0.0a6

**Date:** 2026-05-09
**Theme:** Last v5 alpha. Dashboard scales to many-project setups via
substring filter, with URL state for sharable filtered views.

## What landed

| SHA | Subject |
|-----|---------|
| `adf39c8` | feat(ui): dashboard project filter + URL state |

## Capabilities (this sprint)

### 1 · Substring filter input

A text input in the project-grid header filters cards by
case-insensitive substring match against `name | path | brief`:

```js
visibleProjects() {
  if (!this.filter || !this.filter.trim()) return this.projects;
  const needle = this.filter.trim().toLowerCase();
  return this.projects.filter((p) => {
    const name = (p.name || '').toLowerCase();
    const path = (p.path || '').toLowerCase();
    const brief = (p.brief || '').toLowerCase();
    return name.includes(needle) || path.includes(needle) || brief.includes(needle);
  });
}
```

150ms input debounce keeps URL writes from happening per keystroke
while still feeling instant.

### 2 · URL state

Same default-omit pattern as v3.0.0a9 (fan-out) and v4.0.0a2 (recall):

```
http://harbormaster.local/?filter=billing
```

Reads on mount via `URLSearchParams.get('filter')`; writes on input
debounced. Preserves any foreign params already in the URL (e.g.
`recall_q`).

### 3 · Match counter + empty state

When the filter is active, the header counter switches from
`X discovered` to `X of Y match`. When zero match, an inline
empty-state message renders with a clear button:

> No projects match `billing`. **clear**

### 4 · Refactor: inline x-data → projectGrid()

The original section had its data fetch inline as
`x-init="(async () => {...})()"`. v5.0.0a6 extracts to a named
factory `projectGrid()` with `init()` / `visibleProjects()` /
`persistToUrl()`. Better separation; future logic (e.g. sort
controls) drops in cleanly.

## Real numbers

- 1/1 v5.0.0a5-retro action item shipped
- 0 PRs opened — merged via `git merge --no-ff`
- 6 new unit tests
- Test suite delta: 696 + 2 skips → **702 + 2 skips**
- `mypy --strict` clean across 49 source files
- `ruff` clean across `src/` and `tests/`
- 0 backwards-incompatible changes — additive UI element + URL params

## What worked

- **Substring across three fields.** Operators rarely remember exact
  project names. Searching across `name + path + brief` lets them
  type fragments like "auth" or "the v3 plan" and still find the
  right card. Lowercasing both sides handles case-insensitivity.
- **150ms debounce on URL writes.** Without debounce, typing 10
  characters writes 10 history entries (even with `replaceState` it's
  CPU work). 150ms is short enough to feel instant, long enough to
  coalesce a typing burst.
- **Empty-state clear button.** A user who types and gets zero matches
  shouldn't have to backspace 8 characters to recover. One-click clear.
- **Refactor while we're here.** The inline x-data pattern was fine
  for v2.0 when the section had three fields. Now with filter,
  visibleProjects, persistToUrl etc., a named factory is clearer.

## What to change / next

- **No filter on the dashboard cards' inline ask form.** v3.0.0a7 ask
  forms render per-card; if a filter hides a card mid-stream, the
  in-progress dispatch isn't aborted. Acceptable — Alpine's
  visibleProjects() doesn't unmount the underlying scope. Flag if
  observed.
- **No sort/group controls.** Filtered list is in discovered order
  (last commit desc). Operators with 50+ projects might want
  alphabetical sort or grouping by lockfile language. Defer.
- **Filter doesn't search inside the project's CLAUDE.md / Serena
  memories.** Substring against ProjectInfo fields only. A future
  full-text search could index those, but that's a separate feature.

## Action items for v5.0.0 GA

1. **Drop alpha + write GA retro.** Bump `__version__` to `5.0.0`,
   write a GA retro covering all 6 phases (a1-a6), tag `v5.0.0`,
   push, verify on PyPI. No new code in the GA tag (mirrors v1-v4
   GA pattern).

## Out-of-scope (still)

- Tauri / Electron desktop UI — no demand.
- Relay-binary path (Path B) — Path C HTTP tunnel covers it.
- IDE extension — MCP works with any MCP client.
- Session-cookie auth + CSRF — defer until multi-operator UI is real.
- pnpm v5 lockfile support — pre-2022 format.
- Manual "trigger reembed now" button — defer until needed.
- Reembed ETA estimation — defer until rate signal stabilises.
- Streaming-chunks stress — defer until streaming path bottlenecks.
- Stuck-writeback escalation tier — defer until observed.
- Configurable stale threshold — defer until needed.
- Keyboard shortcut help popover — defer.
- Sort/group controls on the dashboard — defer.
- Full-text search inside CLAUDE.md / Serena memories — defer.

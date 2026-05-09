# Sprint Retro — Harbormaster v4.0.0a4

**Date:** 2026-05-09
**Theme:** Removed the visible round-trip after asking a project. The
trajectory section now updates instantly with an optimistic entry,
then reconciles with the server on the next load.

## What landed

| SHA | Subject |
|-----|---------|
| `e8dfe80` | feat(ui): optimistic trajectory insert (v4.0.0a4) |

## Capabilities (this sprint)

### 1 · `hm:trajectory:append` event with synthetic entry

`askForm()` and `delegateForm()` dispatch a new `:append` event on
stream completion carrying a fully-formed Q&A entry:

```js
{
  id: 'optimistic-' + Date.now(),
  project, host,
  tool: 'ask_project' | 'delegate_task',
  question, answer: streamText,
  timestamp_s: Date.now() / 1000,
  _optimistic: true,
}
```

`trajectoryList.prepend(entry)` adds it to the top of the list
(deduplicating by id). The `_optimistic: true` marker is the
reconciliation key for the next load().

### 2 · Reconciliation on next load()

`load()` reads `/api/trajectories` and:

1. Filters existing entries to keep only those that are `_optimistic`
   AND have no matching server entry yet
   (matched by `project + tool + question`)
2. Prepends those orphan optimistics to the fresh server list
3. Result: server-assigned entries replace their optimistic
   counterparts; in-flight writeback optimistics stay visible

The next dirty event (or operator-initiated reload) eventually
resolves all optimistics.

### 3 · Visual differentiation

Optimistic entries render with:
- `border-cyan-700/40` (cyan instead of gray)
- `bg-cyan-950/30` (subtle cyan tint)
- "● new" cyan badge in the metadata row

So operators can see at a glance "this Q&A is freshly added but
not yet confirmed by the server."

## Real numbers

- 1/1 v4.0.0a3-retro action item shipped
- 0 PRs opened — merged via `git merge --no-ff`
- 5 new unit tests
- Test suite delta: 645 + 2 skips → **650 + 2 skips**
- `mypy --strict` clean across 48 source files
- `ruff` clean across `src/` and `tests/`
- 0 backwards-incompatible changes — additive event + render path

## What worked

- **Reconciliation by content tuple, not by id.** The optimistic
  id (`optimistic-1715260000000`) will never match a server id
  (sqlite rowid). Matching by `(project, tool, question)` survives
  this — and a duplicate question being asked twice would need
  an extra disambiguation step (timestamp). Today the round-trip
  is fast enough that double-fires aren't observed in practice.
- **Two events instead of one.** `hm:trajectory:append` for instant
  feedback; `hm:trajectory:dirty` (kept from v3.0.0a8) for
  background reconciliation. Two-phase commit pattern at the UI
  layer; either event alone gives a degraded but working UX.
- **`_optimistic: true` flag survives the reconcile.** Used both
  by the filter logic AND by the visual differentiation. One
  field, two responsibilities, both needed.

## What to change / next

- **No animation when reconciling.** Optimistic → real swap is
  instant; a 200ms cross-fade would feel polished but adds Alpine
  transition complexity. Defer until someone notices.
- **No client-side "writeback in progress" indicator.** Operators
  see the cyan badge until reconciliation completes. If writeback
  takes >5s (unusual) the badge stays around for a while; a
  spinner overlay could clarify but adds complexity. Defer.

## Action items for the next sprint (v4.0.0a5)

1. **Auto-reembed on drift detection.** `QAStore.open()` currently
   warns on embedding model drift; v4.0.0a5 adds an opt-in
   `[history] auto_reembed_on_drift = true` that triggers the
   reembed CLI flow in-process so operators don't have to run it
   manually. New `/api/history/state` endpoint reports phase
   (idle / running / failed).

## Out-of-scope (still)

- Tauri / Electron desktop UI — no demand.
- Relay-binary path (Path B) — Path C HTTP tunnel covers it.
- IDE extension — MCP works with any MCP client.
- pnpm v5 lockfile support — pre-2022 format.
- Multi-worker dispatch pool — gated on profile evidence in v4.0.0a6.
- Session-cookie auth + CSRF — defer until multi-operator UI is real.
- SSE end-to-end browser test — needs backend mocking; defer to a6.
- IE11 / pre-2018 clipboard fallback — modern-browser-only is fine.
- Double-tap-to-reset / keyboard shortcuts on graph zoom — defer.
- Reconciliation cross-fade / writeback spinner — defer until noticed.

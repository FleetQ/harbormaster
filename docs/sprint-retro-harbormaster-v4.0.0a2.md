# Sprint Retro — Harbormaster v4.0.0a2

**Date:** 2026-05-09
**Theme:** URL state pattern from v3.0.0a9 spread to two more surfaces;
operators can now share recall searches and fan-out queries by URL.

## What landed

| SHA | Subject |
|-----|---------|
| `b5d1a20` | feat(ui): URL state on /api/recall + copy-link affordance |

## Capabilities (this sprint)

### 1 · Recall panel URL state

Dashboard recall panel now reads `recall_q`, `recall_project`,
`recall_host` from the URL on mount, and writes them on each search.
Auto-runs the search when `recall_q` is carried in. Param keys are
prefixed (`recall_*`) so they don't collide with `/tools/fan-out`'s
unprefixed `q`/`host`/etc. when both sets of state appear in one URL.

```
http://harbormaster.local/?recall_q=auth%20flow&recall_project=billing&recall_host=all
```

`persistToUrl()` preserves any foreign params (graph filters etc.)
already in the URL — only the recall-prefixed keys are touched.

### 2 · Fan-out copy-link button

`/tools/fan-out` now has a `copy link` button next to Run. Clicking:

1. Calls `persistToUrl()` to ensure the URL reflects current form state
2. Copies `window.location.href` via `navigator.clipboard.writeText`
3. Flips `shareLinkCopied = true` for 2s feedback ("copied ✓")
4. Falls back to `console.warn` on older browsers / file:// origins

Disabled when question length < 3 (same gate as the Run button).

## Real numbers

- 1/1 v4.0.0a1-retro action item shipped
- 0 PRs opened — merged via `git merge --no-ff`
- 5 new unit tests
- Test suite delta: 635 + 2 skips → **640 + 2 skips**
- `mypy --strict` clean across 48 source files
- `ruff` clean across `src/` and `tests/`
- 0 backwards-incompatible changes — additive URL params + button

## What worked

- **Param prefix scheme.** `recall_*` for the recall panel vs. bare
  `q`/`host`/etc. for fan-out. Avoids collisions when a single URL
  carries both kinds of state. Future surfaces follow the same rule.
- **Preserve-foreign-params.** `persistToUrl()` reads the current
  search params first, mutates only its own keys, and re-serializes.
  Means another panel's URL state survives recall searches.
- **Auto-search on URL-carried question.** A shared link with
  `recall_q=...` doesn't just pre-fill the input — it runs the
  search immediately. Saves the recipient one click.
- **Copy-link feedback timer.** `setTimeout(... 2000)` resets the
  "copied ✓" pseudo-button so the operator sees confirmation
  without a permanent state change.

## What to change / next

- **No `clipboard.writeText` fallback for very old browsers.** On
  pre-2018 Safari / IE11 the fallback is `console.warn` plus the
  URL printed to console. Acceptable — operator UI, modern browsers
  in scope.
- **No "share link" affordance on the recall panel.** Operators can
  copy the URL bar manually after a search. A future phase could
  add a button there too if the asymmetry chafes.

## Action items for the next sprint (v4.0.0a3)

1. **Graph pinch-zoom for mobile.** Wrap the Mermaid SVG in a
   transform container with pinch-zoom + drag-pan handlers. Pure
   JS (no library); CSS `transform: scale() translate()`. Reset
   button to return to scale=1.

## Out-of-scope (still)

- Tauri / Electron desktop UI — no demand.
- Relay-binary path (Path B) — Path C HTTP tunnel covers it.
- IDE extension — MCP works with any MCP client.
- pnpm v5 lockfile support — pre-2022 format.
- Multi-worker dispatch pool — gated on profile evidence in v4.0.0a6.
- Session-cookie auth + CSRF — defer until multi-operator UI is real.
- SSE end-to-end browser test — needs backend mocking; defer to a6.
- IE11 / pre-2018 clipboard fallback — modern-browser-only is fine.

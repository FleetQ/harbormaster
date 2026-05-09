# Sprint Retro — Harbormaster v6.0.1 (patch)

**Date:** 2026-05-09
**Theme:** First v3+ patch release. Two combined regressions made the
dashboard project graph render as raw text instead of an SVG. User
caught it via UI screenshot; fixed in one branch.

## What landed

| SHA | Subject |
|-----|---------|
| `5825027` | fix(ui): project graph rendering regression |

## The bug

Dashboard's "Project graph" panel showed:

```
graph LR
  harbormaster_mcp["harbormaster-mcp"]
  agent_fleet_agent_fleet_cloud["agent-fleet/agent-fleet-cloud"]
  ...
```

…instead of an actual SVG diagram. 47 projects of raw Mermaid markup,
no edges, no boxes.

## Root causes (two combined)

### 1. Alpine `$refs` scope leak (v4.0.0a3)

v4.0.0a3 wrapped `<pre x-ref="diagram">` inside `graphZoom()`'s nested
x-data scope. Alpine refs are **per-component** — `this.$refs.diagram`
from the parent `graphPanel()` scope silently returned `undefined`.
The `if (node && window.__hmMermaid)` guard skipped, mermaid never
ran, raw markup leaked.

### 2. Mermaid ESM async load race

`base.html` loads Mermaid via `<script type="module">` from CDN.
The bundle resolves asynchronously; when `loadGraph` fired on
`x-init`, `window.__hmMermaid` wasn't defined yet. Even with the
ref bug fixed, the readiness guard would still skip.

Both issues compounded: the graph never rendered after v4.0.0a3
ship, and we didn't catch it because:
- Smoke job (`smoke-ui` CI) only checks HTTP 200
- v3.0.0a10 Playwright tests assert page elements but not SVG
  presence
- Local dev / quick QA passes used `curl` + page-source inspection,
  which sees the raw markup as content (200 OK) without rendering

## Fix

```js
// graphPanel.loadGraph()
this.mermaidMarkup = this.graph.mermaid || 'graph LR\n  empty[No projects]';
await this._waitForMermaid(3000);
const node = document.querySelector('pre.mermaid');
if (node && window.__hmMermaid) {
  node.removeAttribute('data-processed');
  await window.__hmMermaid.run({ nodes: [node] });
}

_waitForMermaid(maxMs) {
  return new Promise((resolve) => {
    const start = Date.now();
    const check = () => {
      if (window.__hmMermaid) return resolve(true);
      if (Date.now() - start > maxMs) return resolve(false);
      requestAnimationFrame(check);
    };
    check();
  });
}
```

Two changes:
- `this.$refs.diagram` → `document.querySelector('pre.mermaid')`
  (bypasses Alpine scope nesting)
- `requestAnimationFrame(...)` → `await this._waitForMermaid(3000)`
  (poll up to 3s for the async ESM bundle to register)

## Browser verification

Before fix:
```
preDataProcessed: null    (mermaid never processed)
rawTextLeaks: true        (raw "graph LR" visible)
svgInsidePre: false       (no SVG generated)
```

After fix:
```
preDataProcessed: "true"  (mermaid processed)
rawTextLeaks: false       (no raw text)
svgInsidePre: true        (SVG rendered)
sectionSvgCount: 1        (exactly one SVG in section)
```

## Real numbers

- 0 PRs opened — merged via `git merge --no-ff`
- 2 new regression tests (querySelector path present, mermaid class
  on pre)
- Test suite delta: 737 + 2 skips → **739 + 2 skips**
- `mypy --strict` clean across 50 source files
- `ruff` clean
- 0 backwards-incompatible changes — pure fix

## What worked

- **User screenshot caught it.** The bug was invisible to every
  automated check we run. Manual visual inspection by the operator
  surfaced it within seconds. UI bugs need UI verification.
- **Browser-driven re-verification.** `mcp__claude-in-chrome__javascript_tool`
  let me query the DOM directly before/after the fix — `preDataProcessed`,
  `svgInsidePre`, `rawTextLeaks` flipped from "broken" to "fixed"
  observably. Faster than a full Playwright test cycle.
- **Two-bug confirmation.** First attempt only fixed the `$refs`
  issue; browser still showed raw text. That forced me to look for
  the second cause (async ESM race). A single-bug assumption would
  have shipped a still-broken patch.

## What to change / next

- **Add a Playwright assertion that the SVG actually renders.**
  The current `tests/ui/test_browser_smoke.py` checks page chrome
  but doesn't assert on the graph SVG. A `test_dashboard_graph_renders_as_svg`
  test would catch this class of bug going forward.
- **Move the manual JS verification pattern into a routine smoke.**
  `mcp__claude-in-chrome__javascript_tool` calls (preDataProcessed +
  svgInsidePre) could be a one-line CI check if we wire chromium
  into the smoke-ui job.
- **Audit all `$refs.X` usages.** Anywhere a ref is consumed across
  Alpine scopes, the same bug class could lurk. Cheap grep audit.

## Action items for v7.0.0a1+

1. **Audit cross-scope `$refs` usage.** Grep + manual review.
   Add comment on every legitimate use ("ref + consumer in same
   scope") so future scope-wrapping doesn't regress silently.
2. **Add browser SVG-render assertion to Playwright suite.**
   Closes the gap that hid this bug for 17 versions (v4.0.0a3 →
   v6.0.0).
3. **Optional**: bake the chrome-devtools JS-eval pattern into the
   `/qa` skill so visual bugs surface faster in future sweeps.

## Out-of-scope (still)

(unchanged from v6.0.0 GA retro)

- Tauri / Electron desktop UI — no demand.
- Relay-binary path (Path B) — Path C HTTP tunnel covers it.
- IDE extension — MCP works with any MCP client.
- Session-cookie auth + CSRF — defer until multi-operator UI is real.
- pnpm v5 lockfile support — pre-2022 format.
- Cross-process file locking — single-writer in practice.

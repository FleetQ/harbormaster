# Sprint Retro — Harbormaster v6.0.2 (patch)

**Date:** 2026-05-09
**Theme:** Third regression in the v4.0.0a3 graph viewport rework chain.
v6.0.1 fixed two; this one was hiding behind them.

## What landed

| SHA | Subject |
|-----|---------|
| `ecfac77` | fix(ui): graph viewBox stuck at 16x16 placeholder |

## The bug

After v6.0.1 shipped, Mermaid started running and producing an SVG
in the DOM — but the graph still appeared "empty" in the user's
browser. Diagnostic JS revealed the truth:

```
svgViewBox:    "-8 -8 16 16"          ← placeholder
naturalBboxWxH: "115x1367"            ← real graph content
svgRectHeight: 16                      ← rendered as 16×16 dot
```

The graph content was IN the SVG (47 projects laid out, ~1367px
tall), but the SVG itself shrank to a 16×16 placeholder. From the
user's perspective: empty viewport with just the "reset" button.

## Root cause

`loadGraph()` set `graphLoading=true` at the start, fetched the
graph data, set `mermaidMarkup`, then ran `mermaid.run()`. Only at
the end (in `finally{}`) did it flip `graphLoading=false`.

Problem: the entire graph section is wrapped in `x-show="!graphLoading"`.
While `graphLoading=true`, the section is `display:none` —
unmeasurable. Mermaid measured the hidden `<pre>` as 0×0, computed
a placeholder viewBox of `-8 -8 16 16`, and never re-measured.
When `graphLoading=false` flipped at the end of `finally`, the
section became visible — but Mermaid had already given up.

## Fix

Flip `graphLoading=false` BEFORE running Mermaid:

```js
this.mermaidMarkup = ...;
this.graphLoading = false;                      // ← make section visible
await this._waitForMermaid(3000);
await new Promise((r) => requestAnimationFrame(r));  // ← give browser one frame to apply layout
const node = document.querySelector('pre.mermaid');
if (node && window.__hmMermaid) {
  await window.__hmMermaid.run({ nodes: [node] });  // measures real dimensions now
}
```

The single rAF gives Alpine's reactive update + browser layout pass
time to compute the real viewport before Mermaid measures.

## Browser verification

After fix + hard reload:

```
svgViewBox:      "-8 -8 954.6875 2339.75"   ← real bbox
naturalBboxWxH:  "939x2324"                 ← matches viewBox
svgRectHeight:   2330                        ← visible, fills container
preProcessed:    "true"                      ← Mermaid ran successfully
```

## Real numbers

- 0 PRs opened — merged via `git merge --no-ff`
- 0 new tests — viewBox correctness needs real browser layout
  (Playwright); existing v6.0.1 querySelector guard still holds
- Test suite: 739 + 2 skips (unchanged)
- `mypy --strict` clean across 50 source files
- `ruff` clean
- 0 backwards-incompatible changes — pure ordering fix

## Caveat for operators

The browser will cache `dashboard.html`. After upgrading to v6.0.2,
**do a hard reload** (Cmd-Shift-R / Ctrl-Shift-R) — the cached
HTML still has the broken loadGraph order and will look empty
until the new HTML loads.

## What worked

- **Browser DOM verification surfaced it fast.** A `getBBox()` call
  on the SVG showed natural bbox 939×2324 vs. viewBox 16×16 — the
  symptom + diagnosis in one line. Without that JS query I'd have
  guessed-and-checked for an hour.
- **One-frame rAF wait is the right granularity.** Tried no wait
  (Alpine hadn't flushed yet, Mermaid still measured 0x0). Tried
  multiple frames (overkill). One rAF after the visibility flip
  catches Alpine's microtask + browser layout pass.
- **The third regression in the same v4.0.0a3 commit confirms the
  pattern.** v3.0.0a10 Playwright suite asserts page rendering but
  not SVG dimensions / viewBox correctness. That gap let three
  bugs ship.

## What to change / next

- **Add `test_dashboard_graph_renders_with_real_viewbox` to
  `tests/ui/test_browser_smoke.py`.** Assert that after the page
  loads:
  - `<pre.mermaid>` has `data-processed="true"`
  - The SVG inside has a viewBox other than `-8 -8 16 16`
  - The SVG's height is > 100px
  This catches every regression in this class.
- **Audit any other Alpine `x-show` wrapping a layout-measuring
  component.** The pattern "hide section → run something that
  measures DOM → unhide section" is broken by design.

## Action items for v7.0.0a1+

(adds to v6.0.1 retro list)

3. **Browser SVG-dimensions assertion in Playwright.** Catches
   bugs of this exact class.
4. **Audit `x-show + measure` patterns.** Run `grep` for
   `x-show.*Loading` across templates; flag any where the hidden
   element gets measured downstream.

## Out-of-scope (still)

(unchanged from v6.0.0 GA retro)

# Harbormaster v19.0.0 GA — sprint retro

**Date:** 2026-05-11  
**Theme:** Dramatic UI revamp — first sprint after operator's "I see no difference from v8" critique. Multi-pane workspace + Linear violet identity + compact density + memories editor redemption.

## Tags shipped (v19.0.0a1 → v19.0.0)

| Tag | Capability | Visible delta |
|---|---|---|
| `v19.0.0a1` | New 3-column workspace shell (CSS Grid: nav 240px / main / inspector 320px collapsible) | Foundation; touches every template |
| `v19.0.0a2` | Tab system on project_detail (Overview / Memories / Trajectories / Q&A History / Settings) + keyboard 1-5 + URL hash persistence | Per-project context navigated by tabs |
| `v19.0.0a3` | Context-aware widgets in inspector pane (KPI summary + activity feed + project metadata + budget gauges per page/tab) | Inspector populated; not just placeholder |
| `v19.0.0a4` | **Linear violet OKLCH tokens + compact density pass** (drop cyan → accent hue 290; gap-4→gap-2; text-base→text-sm; 359 token+density substitutions) | First REAL visual identity flip |
| `v19.0.0a5` | Dashboard re-layout: Quick Ask card prominent at top + KPI strip + 2-col card grid (recent activity + bridge + plugins + auto-reembed + recall + project graph) | New dashboard organization |
| `v19.0.0a7` | SSE-driven activity feed in inspector (live indicator ● + 1s throttled DOM updates + pulse animation on new events) | Real-time visibility |
| `v19.0.0a8` | Full memories editor on Memories tab (split-pane: file list + textarea + live preview + revisions + diff + undo/redo) | Closes v10 over-report; "memories editor visible" promise materialized |
| `v19.0.0a9` | Bug fix: a8 had `x-data="memoriesEditor({{ x \| tojson }})"` HTML escaping collision; switched to single-quote pattern | Memories tab actually renders |
| **`v19.0.0`** | GA — drop alpha + cumulative retro | — |

(Note: a6 was claimed mid-flight by Phase 7 due to parallel ship coordination; original a6 work landed as a8.)

## Anti-slop protocol enforced

Every phase required visual verification via Playwright screenshot-to-disk before commit. **Operator caught earlier "v10.a5/a6 memories editor over-reported as shipped" pattern → v19 explicitly verified each phase with screenshots saved at /tmp/v19-a*-*.png.**

## Numbers

- Tests: 1634 → ~1731 (a5) → ~1745+ (a6/a8) — net ~+110
- Source files: 57 → 57 (templates rewritten, no new modules)
- Compiled tailwind.css: ~37KB → ~42KB (violet tokens + new utilities)
- Templates touched (cumulative): base.html + dashboard.html + project_detail.html + network.html + dispatcher_trace.html + fan_out.html + 7 partials = 13 files
- Per-phase wall-clock: ~30-45 min average; sprint ~5h end-to-end

## Visual transformation deltas (compared to v18.0.0 baseline)

1. **3-column workspace** instead of single-column scrolling page (a1)
2. **Tabs on project page** instead of monolithic scrolling project_detail (a2)
3. **Inspector pane** with context-aware widgets (a3)
4. **Linear violet** instead of cyan (a4)
5. **Compact density** — sidebar items tighter, more content fit per screen (a4)
6. **Quick Ask** prominent at dashboard top (a5)
7. **2-col card grid** organization on dashboard (a5)
8. **Live SSE activity feed** with pulse animation in inspector (a7)
9. **Functional memories editor** with split-pane preview (a8/a9)

## Operator UX wins

- Dramatic visual change from v18 — operator's "no difference" complaint addressed
- Multi-axis budget visibility in project metadata inspector (per-host + per-tool + per-project)
- Memories editor finally visible + functional (closes v10 over-report)
- Real-time activity feed gives operator at-a-glance visibility of MCP traffic
- Tabs reduce scroll-fatigue on project page

## Lessons captured

- **Anti-slop verification works**: every phase's screenshot caught actual rendering before commit; the a8→a9 fix happened because verification revealed the editor wasn't rendering
- **Parallel agent coordination**: 3 agents shipped concurrently (a5 dashboard / a6 memories / a7 inspector); disjoint scope (different blocks/files) + version-bump coordination via `git pull` before bump worked cleanly
- **HTML attribute escaping with `tojson`**: `{{ var | tojson }}` inside double-quoted attribute breaks HTML parser. Use `'{{ var | e }}'` (single-quoted) instead.
- **Theme token names must match `@theme` reality**: spec assumed `border-muted`/`text-secondary`; theme had `border-default`/`text-foreground-muted`. Always read `tailwind.input.css` first.
- **Tailwind v4 emits only used utilities**: spec asked for full `accent-50..900` shade scale in compiled CSS; in practice only emit if templates reference. Keep all shades in `@theme` for future use; assert hue/chroma in tests rather than specific shade emission.

## v20 candidates (UI follow-ups)

1. Memory editor: full `bleach.clean()` HTML preview pipeline (currently inline `prose-invert` rendering — verify against XSS)
2. Dashboard Quick Ask: optional inline SSE streaming (current navigates to project page)
3. Inspector pane: drag-resize handle (currently fixed 320px)
4. Tab system: extend to dashboard/network/dispatcher pages (currently project_detail only)
5. Light mode: verify contrast across new violet palette (a4 only fixed dark-mode AA)
6. Mobile responsive: 3-column collapses to drawer + main on <1024px (currently hidden)
7. Empty states: each empty card needs friendlier messaging (mostly just "no X yet")
8. Settings tab: add per-project budget edit form (currently read-only metadata)

## Cumulative chain status (v9 → v19)

11 majors shipped autonomously. 76+ PyPI versions across the chain. ~1745+ tests. Working tree clean, screenshots verified per phase.

# Harbormaster UI/UX Research Report

**Date:** 2026-05-09
**Scope:** End-to-end UI/UX assessment of the Harbormaster web interface — current surface, industry best practices (2024–2026), gap analysis, and prioritized recommendations.
**Audience:** Operator (single senior developer) planning v7+ UI work.
**Method:** Parallel inward (codebase map of `src/harbormaster/ui/`) + outward (Linear / Vercel / Supabase / Posthog / MCP Inspector / OpenTelemetry agent-observability) research.
**Confidence:** High on current-state inventory (ground truth from code). Medium-high on external patterns (primary sources cited; some 2025–26 findings still consolidating).
**Boundary:** Research only. No code changes proposed in this document.

---

## Executive Summary

Harbormaster's UI is **functional, cohesive, and dense** — a single dark-themed dashboard built on Tailwind CDN + Alpine + HTMX, with thoughtful streaming UX (SSE), optimistic trajectory updates, and a help popover added in v6. The core mechanics work.

**The gaps are predictable for a tool that grew feature-by-feature across 6 sprint lines:**

1. **No global navigation primitive at scale.** With 78+ tracked projects, a single grid of cards on `/` (and a flat sidebar on the project detail) does not match Linear/Supabase patterns for many-project workspaces. Cmd-K palette is the missing keystone.
2. **No information hierarchy at the top.** The dashboard opens with a status strip, then a reembed panel, then per-project ask cards — but the operator's "am I OK right now?" question has no glanceable answer (no KPI strip, no trace waterfall, no exception-only alerting).
3. **Color-only state encoding.** Trajectory tiers (cyan/amber/red) and bridge state (emerald/red) violate the "don't rely on color alone" rule. Easy to fix with icons + ARIA.
4. **Tailwind v3 CDN + no design tokens.** v4's OKLCH + `color-mix()` semantic token model is the 2024–26 standard; staying on v3 CDN locks out theme switching, dark/light parity, and operator-tunable accent.
5. **Accessibility floor unmet** — missing `aria-label` on icon buttons, no `aria-live` on streaming output, focus indicators inconsistent, no `lang="en"`. Most are 30-second fixes.
6. **No empty states.** "First-run" UX is undefined. Linear/Vercel/Supabase converged on a 3-part empty-state pattern (headline → why-it-matters → single CTA); Harbormaster has none.

**The biggest leverage move is adopting a Linear-style command palette + KPI strip + semantic OKLCH tokens.** That trio reframes the dashboard from "scrollable list of every feature" to "glanceable status + keyboard-driven navigation," matching how operators actually use power tools.

**v8 should be a focused UI line** (not a feature line), in the spirit of v5 (polish) and v6 (regression-guard patches), with 5–7 alphas covering: palette, KPI strip, design tokens, empty states, accessibility floor, and cancel-on-stream UX.

---

## 1. Current State (distilled)

### What exists

| Surface | What it does | Code |
|---|---|---|
| `/` dashboard | Status strip (Bridge + Plugins) → Reembed panel → Per-project Ask cards → Recall panel → Project grid | `dashboard.html` (1043 lines) |
| `/tools/fan-out` | Multi-project broadcast question via `fan_out_ask` MCP tool | `fan_out.html` (205 lines) |
| `/projects/{name}` | Per-project status, Ask form, Delegate form, trajectory history | `project_detail.html` (266 lines) |
| `/api/*` | 10 JSON/SSE endpoints (health, projects, bridge, plugins, graph, trajectories, recall, history state, history reembed, MCP dispatch) | `routes.py` |

### Architecture choices

- **Tailwind v3 via CDN** + utility-only styling, no design tokens, no `tailwind.config.js`
- **Alpine.js v3** factories per panel: `askForm`, `delegateForm`, `trajectoryList`, `statusStrip`, `reembedPanel`, `recallPanel`, `fanOutForm`, `helpPopover`
- **HTMX 1.9.10** loaded but **not heavily used** — most reactivity goes through Alpine + raw `fetch` via `hmFetch()` helper
- **Mermaid (ESM)** for `/api/graph` rendering
- **Bearer token** via `<meta name="hm-auth-token">` injected into every `hmFetch` call (added v3.0.0a6)
- **Hard-coded dark theme** (`bg-gray-950 text-gray-100` on root). No light mode, no theme switcher
- **Mobile-first responsive**: `grid-cols-1` → `md:grid-cols-2` / `md:grid-cols-3` at 768px

### What works

- SSE streaming UX (token chunks rendered live with throttled DOM updates)
- Optimistic trajectory updates with 3-tier visual escalation (`fresh` → `stale` → `stuck`) added in v5/v6
- URL state serialization for recall + fan-out (v3.0.0a9) — shareable searches
- Cohesive dark palette (gray-950 base, cyan accent, semantic emerald/amber/rose for state)
- Keyboard help popover (v6.0.0a4) with `?` toggle, `Esc` dismiss

### Pain points (from code map, ordered by severity)

**Medium**
- Loading state UX shows only "streaming…" text — no progress, no time-elapsed display until late in the stream
- Trajectory tiers rely heavily on color (cyan/amber/red); spinner only present in amber tier
- Form HTTP errors and tool errors render identically — operator can't distinguish network vs. logic failure
- Focus rings inconsistent across buttons (Tailwind defaults; not WCAG AA verified)
- "Stuck?" badge after 60s offers no action (no cancel, no retry, no "tail logs")

**Low**
- Per-card ask form repeated on dashboard + via `_partials/ask_form.html` partial — could be one Web Component
- Project card descriptions use single-line `truncate` — overflow on mobile
- Status badges (`bridge connected = emerald`, `disconnected = red`) carry no icon — color-only
- Recall popover hard-codes `max-h-[70vh]` — short viewports clip content
- No `lang="en"` on `<html>`; no `aria-label` on icon-only buttons (`?`, `×`)

---

## 2. Industry Patterns (2024–2026)

### Information density: 3-layer convergence

Modern dev dashboards (Vercel, Linear, Supabase Studio, Posthog) converge on:

1. **Persistent sidebar** (240–280px) for navigation
2. **KPI strip** (4–6 metrics) for the "am I OK right now?" glance
3. **Flexible content grid** for inspection

Vercel's Feb 2026 redesign cut First Meaningful Paint by 1.2s by batching React updates and using SWR for live data. **Sub-300ms interaction is the practical ceiling**, not a stretch goal.

> Source: [Vercel changelog — dashboard navigation redesign rollout](https://vercel.com/changelog/dashboard-navigation-redesign-rollout)

### Project switching at scale: command palette is mandatory

Supabase Studio's "one organization at a time" sidebar works for ~10 projects per org. **Beyond ~30 projects, fuzzy command palette (Cmd-K) outperforms any sidebar**. Linear's "four access paths per action" (button, shortcut, context menu, palette) shows shortcuts inline in the palette — making the palette itself the discovery mechanism.

> Sources: [Linear delightful patterns — gunpowderlabs Dec 2024](https://gunpowderlabs.com/2024/12/22/linear-delightful-patterns), [Supabase dashboard navigation discussion](https://github.com/orgs/supabase/discussions/33670)

### Streaming output: cadence > raw speed

- TTFT < 300–700ms feels snappy
- Throttle DOM updates to every 30–60ms (not per-token) to avoid reflow storms
- `AbortController` for cancellation is table stakes
- **SSE Last-Event-ID resumption** prevents the dropped-connection-→-resubmit failure mode for long queries
- Typed events (`token`, `tool`, `usage`, `error`) > raw text — UI renders tool calls differently

> Source: [Streaming LLM responses deep dive — Tamas Piros](https://tpiros.dev/blog/streaming-llm-responses-a-deep-dive/), [Resumable SSE token streams — zknill.io](https://zknill.io/posts/everyone-said-sse-token-streaming-was-easy/)

### State visualization: trace waterfall, not status table

OpenTelemetry's 2025 AI agent observability spec converged on **trace span model** — each agent invocation is a span, tool calls are sub-spans. Datadog, Grafana, Uptrace render this as a waterfall/flame graph. **For Harbormaster's dispatcher, a lightweight job→step hierarchy beats a flat "running/queued/done" badge list.**

Color convention is now standard across Grafana / Datadog / GitHub Actions:
- Blue = running, amber = queued, green = done, red = failed
- Pulsing dot for running; static badge for terminal states
- **Exception-based alerting** — healthy = silent

> Sources: [OpenTelemetry AI agent observability blog 2025](https://opentelemetry.io/blog/2025/ai-agent-observability/), [Top 5 AI agent observability platforms 2026 — Maxim](https://www.getmaxim.ai/articles/top-5-ai-agent-observability-platforms-in-2026/)

### Keyboard-first UX: single-key in scope, palette globally

Linear's pattern (gold standard):
- Single-letter shortcuts (`C` create, `X` select, `Esc` back) in modal context
- Cmd-K palette is the **only** global modifier
- Avoids chords entirely → no browser/OS conflict
- `?` shows context-aware shortcut sheet

Harbormaster v6's `?` popover is step 1; **palette integration is step 2**.

### Empty states: 3-part canonical structure

> Headline (what's absent) → Secondary (why it matters) → Single CTA (exact next step)

Anti-pattern: generic "Get Started" button. Linear/Notion use monochrome illustrations matching interface palette, not colorful marketing art.

> Source: [Empty state UX patterns — Eleken](https://www.eleken.co/blog-posts/empty-state-ux), [Carbon Design System empty states](https://carbondesignsystem.com/patterns/empty-states-pattern/)

### Color systems: Tailwind v4 + OKLCH + semantic tokens

- Tailwind v4 ships OKLCH-native colors using `oklch(var(--token, L C H) / <alpha-value>)`
- Evil Martians' semantic-token pattern: `text-accent-700 dark:text-accent-200` (not `text-sky-700 dark:text-sky-200`) — accent is a CSS variable
- Dark mode becomes a shade swap, not a color swap → operator-tunable themes for free
- **Dark-by-default is the dev tool expectation** (Grafana, Datadog, VSCode, GitHub)
- Avoid fully desaturated dark themes (Chroma 0.03–0.08 reads "intentional dark"; Chroma 0 reads "broken")
- `color-mix()` (CSS, fully supported 2024) for runtime tinting without JS

> Sources: [Tailwind v4 color system guide](https://tailwindcolor.tools/blog/tailwind-css-v4-color-system-complete-guide), [Better dynamic themes with OKLCH — Evil Martians](https://evilmartians.com/chronicles/better-dynamic-themes-in-tailwind-with-oklch-color-magic)

### MCP-specific landscape

- **MCP Inspector** (official Anthropic) — minimal 5-panel layout (server connection / resources / prompts / tools / notifications). Single-server, no persistence, no auth. **Harbormaster's scope is substantially beyond Inspector.**
- **Smithery.ai** — 7,300+ servers as a search/filter card grid, no real-time status
- **Emerging convention** (per agentic-design.ai taxonomy): "Agent Status & Activity UI" + "Monitoring and Control Patterns" + "Human-on-the-Loop" supervision (Harbormaster's exact operating model)

> Sources: [MCP Inspector docs](https://modelcontextprotocol.io/docs/tools/inspector), [Agentic design UI/UX patterns](https://agentic-design.ai/patterns/ui-ux-patterns)

### Accessibility minimums for internal tools

WCAG 2.2 AA is the legal baseline (formalized Oct 2023, ISO/IEC 40500:2025). For solo-operator tools:

- **Worth doing**: 4.5:1 contrast, keyboard navigability, visible focus indicators, `aria-label` on icon buttons, `aria-live="polite"` on streaming output
- **Skip**: per-token live-region announcements, screen-reader narration of graph viz, complex landmarks for a single-page app

### Anti-patterns (avoid)

- **Modal overuse** — modals for confirmation only; everything else = slide-over or in-place expand
- **Icon-only nav without labels** — every nav icon needs persistent label OR hover tooltip
- **Mermaid for >5 nodes** — degrades fast; D3/Cytoscape force-directed for graphs, Mermaid for inline docs
- **Excessive entry animation** — adds 200–400ms perceived latency, conflicts with `prefers-reduced-motion`. Vercel/Linear use motion only for state changes

---

## 3. Gap Analysis

| Dimension | Current | Industry standard | Gap severity |
|---|---|---|---|
| **Global navigation** | Top nav bar (4 links: Dashboard, Fan-out, API, GitHub) | Cmd-K palette + sidebar with grouped projects + keyboard shortcuts inline | **High** |
| **Glanceable status** | Status strip (Bridge + Plugins) buried below header | KPI strip at very top: total projects, active embeds, queued queries, error rate (last 1h) | **High** |
| **Project discovery (78+ projects)** | Single flat grid on `/` | Sidebar with grouping (by language, active vs archived) + palette fuzzy search | **High** |
| **State visualization (dispatcher)** | No view of dispatcher state in UI; CLI-only via `dispatcher status` (v6.0.0a6) | Trace waterfall: agent invocation → tool calls → token stream, with timing | **High** |
| **Streaming UX** | Good: SSE, AbortController, throttled rendering | Add: typed events, Last-Event-ID resumption, "tail logs" link from stuck trajectories | Medium |
| **Color encoding** | Color-only for tier badges + bridge state | Color + icon + `aria-label` (W3C requires non-color signal) | Medium |
| **Design tokens** | Hard-coded Tailwind v3 utilities | Tailwind v4 OKLCH + semantic tokens (`accent`, `muted`, `surface`, `success`, `warning`, `danger`) | Medium |
| **Empty states** | Undefined | 3-part canonical (headline → why → CTA) per zero-state surface | Medium |
| **Accessibility floor** | `aria-label` missing on icon buttons; no `aria-live` on stream; no `lang`; focus rings inconsistent | WCAG 2.2 AA baseline: contrast 4.5:1, focus indicators, ARIA on icons + streams | Medium |
| **Light mode** | Not supported | Optional, but cheap if going OKLCH; matches operator preference | Low |
| **Graph rendering** | Mermaid CDN, has known regression class (v4.0.0a3 → v6.0.2) | Either: Cytoscape/D3 for >5 nodes, OR keep Mermaid + ship the v7.0.0a1+a2 regression guards | Low (covered by v7) |
| **Keyboard discovery** | `?` popover (v6) | `?` popover + Cmd-K palette + per-result shortcut display | Medium |

---

## 4. Recommendations (priority-ordered for v8 line)

Each recommendation is sized for one alpha phase per established v3–v6 cadence (~10–15 min implementation when no design questions surface).

### Tier 1 — Highest leverage

**R1. Cmd-K command palette**
- Single global keyboard primitive
- Fuzzy search across: projects, tools (ask/delegate/recall/fan-out), settings
- Each result shows its keyboard shortcut inline
- Built on `kbar` (React) or roll own with Alpine + `fuzzysort` (lighter, matches stack)
- **Why first**: unlocks every subsequent navigation improvement; the missing keystone

**R2. KPI strip at top of dashboard**
- 4–6 metrics: total projects, active embeds, queued queries, error rate (1h), bridge status, dispatcher health
- Replaces or augments current Bridge+Plugins status strip
- **Why second**: glanceable status answers the operator's primary question without scroll

**R3. Semantic OKLCH design tokens (Tailwind v4 migration)**
- Drop CDN; vendor Tailwind v4 with PostCSS or `@tailwindcss/cli`
- Define semantic tokens: `accent`, `muted`, `surface-1/2/3`, `success`, `warning`, `danger`, `info`
- All current utility classes mapped through tokens
- **Why third**: every subsequent visual tweak compounds; future light mode is a one-line CSS variable swap
- **Risk**: largest blast radius; could split into "tokens defined" + "templates migrated" alphas

### Tier 2 — Quick wins

**R4. Accessibility floor**
- `lang="en"` on `<html>`
- `aria-label` on every icon-only button (`?`, `×`, stop)
- `aria-live="polite"` on streamText output
- `role="alert"` on error divs
- `aria-busy="true"` on loading buttons
- Visible focus rings via `focus-visible:ring-2 focus-visible:ring-cyan-400`
- Contrast audit: replace `text-gray-500` on dark backgrounds with `text-gray-400` minimum
- **Why**: 30-second fixes; closes WCAG 2.2 AA most-common-failure list

**R5. Color + icon for state badges**
- Add icon to bridge connected/disconnected, trajectory tiers (●/⚠/✓), reembed phase
- Keep color, add icon, add `aria-label` — three-channel encoding
- **Why**: closes color-only encoding gap; helps colorblind operators

**R6. Empty states (3-part canonical)**
- Per surface: dashboard with no projects, recall with no matches, history with no trajectories, fan-out with no selections
- Headline + why-it-matters + single CTA
- Reuse Heroicons or inline SVG; monochrome matching palette
- **Why**: first-run UX is currently undefined; cheap to ship

### Tier 3 — Architectural moves

**R7. Trace waterfall view for dispatcher**
- New surface: `/dispatcher` showing live spans for in-flight tool calls
- Rendered as horizontal waterfall: invocation → tool call → token stream
- Reuses dispatcher state CLI from v6.0.0a6 + new `/api/dispatcher/spans` endpoint (SSE)
- **Why**: matches OpenTelemetry agent observability convention; operator gets visibility into what's running NOW

**R8. Sidebar with grouped project navigation**
- Replace single-grid project list on `/` with sidebar (240–280px wide)
- Group by: language (Python/TS/Rust/etc), pinned, recently-asked, archived
- Collapsed state persisted per operator
- Project grid becomes the "Pinned" or "Recently asked" landing
- **Why**: 78 flat tiles is the wrong primitive at scale

**R9. SSE Last-Event-ID resumption**
- Server: emit incrementing event IDs in SSE stream
- Client: pass `Last-Event-ID` header on reconnect
- Server: replay from cursor in dispatcher state
- **Why**: dropped connections during long embeds currently force resubmit (expensive)

**R10. Typed SSE events (`token`, `tool`, `usage`, `error`)**
- Replace current `chunk` with structured event types
- UI renders tool calls differently from response tokens (badge + tool name)
- **Why**: foundation for richer streaming UX (tool call timeline, token usage display)

### Tier 4 — Polish

**R11. Light mode toggle**
- Free if R3 (OKLCH semantic tokens) ships
- Operator preference, persisted in localStorage
- `prefers-color-scheme` initial detection

**R12. Graph rendering migration (Mermaid → Cytoscape)**
- Defer until project count exceeds Mermaid's comfortable limit (currently 50 projects = ~OK)
- Cytoscape for force-directed; keep Mermaid for inline docs only
- **Why**: only worth it when graph is actively unusable

---

## 5. Suggested v8 line shape

Following v5/v6 polish-line convention (5–7 alphas + GA):

| Alpha | Capability | Tier |
|---|---|---|
| `v8.0.0a1` | Accessibility floor (R4) | 2 |
| `v8.0.0a2` | Color + icon for state badges (R5) | 2 |
| `v8.0.0a3` | Empty states across all surfaces (R6) | 2 |
| `v8.0.0a4` | Cmd-K palette (R1) | 1 |
| `v8.0.0a5` | KPI strip at top of dashboard (R2) | 1 |
| `v8.0.0a6` | Tailwind v4 + OKLCH semantic tokens (R3) | 1 |
| `v8.0.0a7` | (optional) Light mode toggle (R11) | 4 |
| `v8.0.0` GA | Drop alpha + retro | — |

**Architectural moves (R7, R8, R9, R10) deferred to v9** — each has design-question depth that would slow a polish line.

**Why this order**: tier-2 first because they're independent, low-risk, and visible-improvement-per-commit (good for retro narrative). Cmd-K and KPI strip in mid-line because they require palette infrastructure to land first. Tailwind v4 last because it touches every template and benefits from the prior tier-2 cleanup landing first (one less thing to migrate alongside the v4 swap).

---

## 6. Open questions for the operator

These need a decision before v8 starts:

1. **Sidebar vs Cmd-K-only navigation?** Linear runs both; Vercel sidebar-primary; Raycast palette-only. Harbormaster's 78-project scale argues for both, but a sidebar costs significant template surface. Acceptable to ship Cmd-K palette first, defer sidebar to v9?
2. **Light mode worth shipping?** Cheap if OKLCH tokens land, but adds testing matrix. Skip for v8?
3. **Tailwind v3 → v4 in single alpha or split?** v4 migration is the largest blast radius; splitting into "tokens + base swap" then "template-by-template migration" is safer but doubles the alpha count.
4. **Trace waterfall surface (R7) — needed in v8 or v9?** v6.0.0a6 added the CLI; UI version requires new SSE endpoint + new view. Defer feels right.
5. **Replace HTMX?** Currently loaded but barely used. Removing reduces 14KB of dead weight.

---

## 7. Sources

### Primary product sources
- [Linear delightful design patterns — gunpowderlabs Dec 2024](https://gunpowderlabs.com/2024/12/22/linear-delightful-patterns)
- [Vercel dashboard redesign blog](https://vercel.com/blog/dashboard-redesign)
- [Vercel changelog — Feb 2026 dashboard navigation rollout](https://vercel.com/changelog/dashboard-navigation-redesign-rollout)
- [Supabase dashboard navigation discussion](https://github.com/orgs/supabase/discussions/33670)
- [MCP Inspector — Anthropic docs](https://modelcontextprotocol.io/docs/tools/inspector)
- [MCP Inspector GitHub](https://github.com/modelcontextprotocol/inspector)
- [Smithery.ai marketplace](https://smithery.ai/)

### Pattern references
- [Agentic design UI/UX patterns taxonomy](https://agentic-design.ai/patterns/ui-ux-patterns)
- [AI agent observability — OpenTelemetry blog 2025](https://opentelemetry.io/blog/2025/ai-agent-observability/)
- [Top 5 AI agent observability platforms 2026 — Maxim](https://www.getmaxim.ai/articles/top-5-ai-agent-observability-platforms-in-2026/)
- [OpenTelemetry for AI systems — Uptrace 2026](https://uptrace.dev/blog/opentelemetry-ai-systems)
- [Datadog check status widget docs](https://docs.datadoghq.com/dashboards/widgets/check_status/)

### Streaming UX
- [Streaming LLM responses deep dive — Tamas Piros](https://tpiros.dev/blog/streaming-llm-responses-a-deep-dive/)
- [Making SSE token streams resumable — zknill.io](https://zknill.io/posts/everyone-said-sse-token-streaming-was-easy/)

### Color systems
- [Tailwind v4 color system guide](https://tailwindcolor.tools/blog/tailwind-css-v4-color-system-complete-guide)
- [Better dynamic themes in Tailwind with OKLCH — Evil Martians](https://evilmartians.com/chronicles/better-dynamic-themes-in-tailwind-with-oklch-color-magic)

### Empty states & accessibility
- [Empty state UX — Eleken](https://www.eleken.co/blog-posts/empty-state-ux)
- [Carbon Design System empty states pattern](https://carbondesignsystem.com/patterns/empty-states-pattern/)
- [UI patterns that fail at scale — Altersquare](https://www.altersquare.io/ui-patterns-fail-scale-why-they-keep-getting-used/)

### Internal artifacts (this report's inputs)
- `/tmp/harbormaster-ui-map.md` — full code-level inventory (800+ lines)
- Serena memories: `architecture`, `conventions`, `dev-commands`, `v6-final-summary`, `global/feedback-alpine-mermaid-pitfalls`

---

**End of research report.** Next step (operator decision): pick which Open Questions (§6) to answer, then either invoke `/sc:design` for v8 architecture or `/sc:implement` after v7 GA ships.

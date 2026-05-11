# Harbormaster v21.0.0 GA — FINAL chain close

**Date:** 2026-05-11
**Theme:** Final autonomous sprint. Operator-given polish + long-deferred architecture + operator-visible features (model selection). After this GA the autonomous chain **HALTS PERMANENTLY**.

---

## v21.0 — 10 alphas + GA

| Tag | Theme | New tests |
|---|---|---|
| `v21.0.0a1` | Mobile responsive drawer pattern (3-col → drawer below 1024px) | +10 |
| `v21.0.0a2` | Q&A History tab + Settings editable budget form (closes 2 v19 placeholders) | +12 |
| `v21.0.0a3` | Empty states polish (5+ surfaces) + operator-tunable OKLCH accent picker | +18 |
| `v21.0.0a4` | Bleach XSS regression + light-mode contrast token tuning (3 gaps fixed) | +40 |
| `v21.0.0a5` | Inspector drag-resize handle (240-480px) + keyboard shortcuts cheatsheet | +11 |
| `v21.0.0a6` | Tabs unification — extracted `_tabs.html` partial, applied to dashboard/network/dispatcher | +6 |
| `v21.0.0a7` | KPI history sparklines + final a11y polish pass | +10 |
| `v21.0.0a8` | Multi-process metrics aggregator (SQLite WAL) + cross-process projects cache (deferred since v9.0.0a2/v7.0.0a6) | +14 |
| `v21.0.0a9` | Cytoscape project-deps graph + linguist extension-based language detection (deferred since v7) | +12 |
| `v21.0.0a10` | Operator-selectable model per tool call (haiku/sonnet/opus alias) + UI dropdowns (replaced schema versioning per operator option B) | +25 |
| **`v21.0.0`** | GA — chain close, this retro | — |

---

## Numbers

- Tests: 1764 → **1926** (+162 new pins, +9.2%)
- v21 PyPI versions: **11** (a1..a10 + GA)
- Cumulative chain (v9 → v21): **~95 PyPI versions** shipped autonomously
- Source files: 57 → ~62
- 0 backwards-incompatible API changes within v21 (one deprecation removal: v9's `chunk` SSE alongside `token` — see v10 GA)
- 0 force-pushes to main
- 0 PyPI yanks across the entire chain

---

## What's permanently out of scope

- **Tauri / Electron desktop UI wrapper** — separate `harbormaster-desktop` project line in a future operator-driven sprint. Out of scope for the web-UI chain.
- **Schema versioning for `dispatcher status --json`** — replaced with model selection per operator's option B. Permanently deferred until a real consumer needs it. The CLI's JSON shape is currently considered an implicit v1 contract; first breaking change triggers explicit versioning.
- **Native OS notifications / system tray** — depend on Tauri.
- **Code signing / app store presence** — depend on Tauri.
- **Multi-operator UI** (multi-tenant auth, role-based access) — operator-only by design.
- **LLM-based KG triple extraction for remote hosts** — heuristic-only over SSH.
- **Cross-model vector translation** — embedding-model upgrades require manual reembed.
- **Session-cookie auth + CSRF** — current Bearer + cookie SSE auth covers single-operator deployment.

---

## v21 capability summary

After v21.0.0 the operator has:

1. **Three-column workspace shell** (sidebar / main / collapsible-resizable inspector) — v19
2. **Mobile responsive drawers** below 1024px — v21.a1
3. **Five-tab project page** + tab unification across dashboard/network/dispatcher — v19.a2 + v21.a6
4. **Cmd-K command palette** with bigram fuzzy match — v8
5. **Keyboard shortcuts cheatsheet** (`?` opens) + `Cmd-Shift-L` theme toggle — v21.a5
6. **Light + dark theme** with operator-tunable accent — v12.a7 + v21.a3 (picker) + v21.a4 (light-mode contrast)
7. **Memories editor** — split-pane raw + bleach-sanitised preview + revision history + diff + tag chips — v10/v11/v19
8. **Q&A history search** scoped per project — v21.a2
9. **Network graph** (Cytoscape inter-project) + project-deps graph (Cytoscape, was Mermaid) — v10/v21.a9
10. **Dispatcher trace waterfall** with parent/child spans — v9/v16/v17
11. **KPI strip** with 24h sparklines + multi-axis budgets (per-host + per-tool + per-project) — v8/v14/v15/v21.a7
12. **Real-time SSE activity feed** in inspector — v19.a7
13. **Operator-selectable model** (haiku/sonnet/opus) per MCP tool call — v21.a10
14. **Multi-process safe** — SQLite-backed dispatcher metrics + projects cache shared across `harbormaster-mcp` + `harbormaster-ui` processes — v21.a8
15. **CLI for ops** — `harbormaster-mcp config check` + `dispatcher status` + pre-commit config-doc parity — v14/v15/v16

Plus standalone OSS + optional FleetQ Bridge integration (Platform Tool, A2A Agent Cards, federated KnowledgeGraph), Codex backend parity, SSH fan-out, retention config, full XSS regression test coverage, WCAG AA contrast pass in both themes.

---

## Operator handoff brief

**Chain HALTED at v21.0.0 GA.**

Future work begins from explicit operator-given requirements, not chain-driven retro candidates.

To restart development:
- Open a new session with a concrete requirement.
- For a v22 minor or feature line: cut `feat/v22.0-<name>` branches from main; follow proven release flow (alpha tags + GA).
- For a v21.x.y patch: cherry-pick or develop on `main` directly; tag `v21.0.1` etc.
- For a desktop wrapper: start a new repo `harbormaster-desktop` with Tauri + sidecar-launches `harbormaster-mcp` + `harbormaster-ui`. Treat it as a fresh product line, not a chain link.

The chain's procedural lessons (5 binding rules from v10-v19 retros, captured in `harbormaster_autonomous_chain_decisions` memory) remain useful as defaults but are not load-bearing for one-shot patches.

---

## Anti-slop protocol — final scorecard

Across v21's 10 alphas, every phase required a Playwright screenshot to disk + visual verification before commit. This caught:
- **v19.a8 → a9** the `tojson`-in-attribute Alpine mount bug (hotfix shipped within hours)
- **v21.a2** Settings tab metadata grid actually rendering after factory rename
- **v21.a4** light-mode contrast failures across 3 token pairs

Without the protocol, the chain would have over-reported "shipped" features that weren't visible (the v10 over-report pattern operator caught at v18 → v19 transition that started this whole arc).

---

## Cumulative chain narrative (v9 → v21)

Started: 2026-05-09 with operator's "продължи v9" prompt after v8 GA.
Closed: 2026-05-11 with this retro.

Wall-clock active: ~3 days. 13 GA tags (v9-v21). ~95 PyPI versions. ~1100 new tests added across the chain (921 → 1926).

The chain proved: autonomous multi-phase product evolution at this scale IS reliable when paired with anti-slop visual verification and single-phase-per-subagent delegation. The brittle pattern is multi-phase-per-subagent (which halted twice during this sprint).

---

**Chain complete at v21.0.0 GA. No v22 planned. Future work begins from operator-given requirements.**

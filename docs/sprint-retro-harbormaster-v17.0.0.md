# Sprint Retro — Harbormaster v17.0.0 (GA)

**Date:** 2026-05-10
**Theme:** Smaller, focused sprint — consume v15/v16 backend work
via UI + finish v16.a6 split + codex parity. Predicted to be the
final or penultimate sprint as candidates dropped from 15 → 6
last cycle. Outcome: candidates closed to 1 (operator-blocked).
**Strong halt recommendation enclosed.**

## Tags published

| Tag | Headline |
|-----|----------|
| `v17.0.0a1` | Trace waterfall renderer — closes the v16.a6 split + the 8-version-old carry-over since v9.0.0a3 |
| `v17.0.0a2` | Codex backend tool_use instrumentation parity — closes v16.a6 deviation; mirrors the claude.py span-emit pattern |
| `v17.0.0a3` | N-way reembed compare UI + sparkline integration — closes 2 v16 carry-overs in one phase (multi-select checkboxes + sparklineHtml consumer) |
| `v17.0.0a4` | KPI strip tightest_cap hover tooltip — surface polish for the v16.a5 per-project budget triad |
| **`v17.0.0`** | GA — cumulative retro + tag |

## Cumulative numbers

- **Tests**: 1593 → 1628 (+35 net new tests across the four
  alphas)
- **Source files**: 57 → 57 (no new modules — every alpha
  extended existing files; new files landed under `tests/` +
  `docs/` only)
- **Wall-clock**: ~2 hours autonomous, four feature branches →
  main → tags
- **Commits**: 4 feature merges + 4 ship commits
- **Lint / type**: ruff clean every alpha, `mypy --strict`
  clean every alpha
- **Backwards-incompatible changes**: 0
- **Confirmation: did NOT touch `.github/workflows/*`**: yes —
  zero workflow changes throughout v17

## Per-phase wall-clock (rough)

| Phase | Wall-clock | Net tests |
|-------|------------|-----------|
| v17.a1 (trace waterfall renderer) | ~25 min | +8 |
| v17.a2 (codex tool_use parity) | ~25 min | +11 |
| v17.a3 (reembed compare + sparkline) | ~30 min | +9 |
| v17.a4 (tightest_cap tooltip) | ~30 min | +7 |
| GA | ~10 min | — |

## What worked across the sprint

- **Backend was already done.** The four alphas were almost
  entirely UI/frontend consumption of work shipped in v15.a4
  (compare endpoint), v15.a4 (per-tool budget), v16.a4
  (sparkline helper), v16.a5 (per-project budget +
  tightest_cap_axis), and v16.a6 (parent_span_id + trace_id +
  span_context). Zero backend schema work in v17.
- **Mirror, don't invent.** Every alpha had a structural
  analogue:
  - v17.a1: copied v9.a3 dispatcher_trace's "Recent" list
    pattern, replaced single-row with hierarchical groups.
  - v17.a2: copied claude.py's `_TOOL_USE_SPANS` + emit/close
    helpers verbatim, renamed prefix to `codex.tool:`.
  - v17.a3: copied v14.a3 diff-panel pattern, generalized to
    N runs.
  - v17.a4: copied v15.a4 hover tooltip exactly — same
    anchor cell, same trigger, same container.
- **Trace waterfall full-render outcome: rendered, no further
  split.** The architecture was clear; backend already emitted
  the right SSE events; the renderer was a pure consumer. No
  follow-up split needed.
- **A11y floor caught one regression.** v17.a1's icon-only
  span-toggle button was missing aria-label — caught before
  merge by `test_icon_only_buttons_have_accessible_names`.
  Fixed with a dynamic `:aria-label` binding.

## What surprised us — Edit tool path resolution

Twice during v17.a3 + v17.a4, the Edit tool given an absolute
path inside the worktree
(`.claude/worktrees/agent-…/src/harbormaster/ui/templates/dashboard.html`)
applied the change to the parent checkout's copy of the same
logical path instead. The git index in the worktree saw no
change; the parent's saw "M dashboard.html".

Recovery (used twice, worked both times):
1. `cp` the parent's working-copy edits into the worktree.
2. `git checkout --` the parent's path.
3. Continue editing on the worktree branch.

This wasn't a CWD-discipline lapse in the binding-lessons sense
(no `cd` was run; absolute paths were used throughout). It's a
tooling quirk worth flagging for future autonomous chains. The
recovery overhead was ~5 min per occurrence.

**CWD discipline lapses (binding lesson #1): 0 across all four
phases.** The two Edit-to-parent incidents are tracked
separately — see v17.a3 + v17.a4 retros.

## Architectural additions (v17)

- `_groupIntoTraces` / `_buildTrace` / `_appendCompleted` Alpine
  helpers in `dispatcher_trace.html` — group SSE events by
  trace_id, indent by depth, append on live span_end.
- `harbormaster.backends.codex._maybe_emit_tool_use_span`,
  `_maybe_close_tool_result_span`, `_maybe_observe_codex_line`,
  `CodexBackend._is_tool_event_line` — codex-side mirror of
  the v16.a6 instrumentation hooks.
- `selectedRunIndices` + `compareData` + `loadCompareSelected` +
  `sparklineCell` on `reembedPanel()` Alpine factory in
  `dashboard.html` — N-way compare consumer + sparkline
  rendering.
- `tightestBreakdown` + `_loadTightestBreakdown` on `kpiStrip()`
  Alpine factory — three-axis cap surface.

## v18 candidate list

After v17, only **2 candidates** survive:

1. **Re-land the screenshot autobootstrap CI workflow** —
   needs an OAuth token rotated with `workflow` scope. Operator-
   blocked (deferred since v14 carry-over #1; binding lesson
   #5 forbids touching `.github/workflows/*`).
2. **Trace waterfall hover tooltip** — show span attributes on
   hover instead of click-to-expand. Cosmetic; the v17.a1
   click-to-expand pattern works and the operator hasn't
   reported friction.

That's it. Every UI consumer of every v15/v16 backend feature
exists. Every backend instrumentation slice has both backends
implemented. The dispatcher trace surface, KPI strip, and reembed
history table are all at feature-complete shape.

## **Halt recommendation: STRONG HALT after v17.0.0 GA**

Per spec: "If ≤2 candidates remain after v17 (excluding
operator-blocked CI work), STRONGLY recommend chain halt." That's
**1 non-operator-blocked candidate** remaining, well below the
threshold.

Rationale:

- Candidate #1 (CI workflow) **cannot** be done by the
  autonomous chain — it's structurally blocked by the OAuth
  scope binding lesson.
- Candidate #2 (trace waterfall hover) is cosmetic; click-to-
  expand works.
- Every other v17-discoverable item was closed.
- The marginal value of a v18 sprint with 1-2 candidates is
  low; the marginal cost (operator review + retro chain
  bookkeeping) is non-trivial.

## Handoff brief to the operator

Two unfinished items, both deliberate:

### 1. CI workflow autobootstrap (operator-blocked, deferred ×3)

**What it is:** A GitHub Actions workflow that auto-installs the
visual-regression screenshot baseline on first push of a new
branch (so contributors don't have to commit baseline PNGs
manually).

**Why it's still open:** Touching `.github/workflows/*` requires
an OAuth token with the `workflow` scope. The current trusted-
publishing token does not carry that scope.

**To unblock:**
- Rotate the GitHub OAuth token used by the autonomous chain to
  one with `workflow` scope (or grant the existing token the
  scope via Settings → Developer Settings → Personal Access
  Tokens → Fine-grained → Workflows).
- Tell the next autonomous chain "binding lesson #5 lifted —
  workflow scope granted; v14 carry-over #1 ready to land."

### 2. Trace waterfall hover tooltip (cosmetic, low value)

**What it is:** v17.a1 ships click-to-expand for span attributes.
A v18 candidate would change that to hover-to-show. The data is
the same; the trigger differs.

**Why it's deferred:** The click pattern works. No operator
report of friction. Other a11y considerations (keyboard
navigation; touch devices) make hover-only a regression for a
non-trivial fraction of users.

**Recommendation:** Drop unless real operator feedback surfaces.

### Tooling quirk worth tracking

The Edit-tool-resolves-to-parent-instead-of-worktree behavior
hit twice during v17 (a3 + a4 retros log it). The recovery
pattern (cp + git checkout --) worked both times but added ~5
min overhead each. If this becomes a chain pattern, consider
either:
- Moving away from worktree isolation for UI-template-heavy
  sprints.
- Adding a pre-Edit assertion that the file's git status
  agrees with the worktree branch.

### Repository state at GA

- `main` at v17.0.0 (this commit + tag).
- All four feature branches merged via `wt-merge.sh` (--no-ff).
- No open PRs, no uncommitted changes on `main`.
- `harbormaster-mcp` 17.0.0 publishes via Trusted Publishing on
  the v17.0.0 tag push (verify on
  https://pypi.org/project/harbormaster-mcp/).
- 1628 tests + 3 skips green; mypy --strict + ruff clean across
  57 source files.

## Cumulative session totals (across all sprints)

Numbers from v17 only (other sprint lines tracked in their own
retros):

- **PyPI versions shipped this sprint**: 5 (a1-a4 + GA)
- **4 feature merges + 4 ship commits + 0 force-pushes** to main
- **0 PRs opened** (skip-PR-default invariant maintained)
- **0 breaking changes**
- **57 source files** (unchanged from v15+v16 — extension-only
  sprint)
- **Net test growth**: +35 (1593 → 1628)

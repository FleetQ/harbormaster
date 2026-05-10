# Sprint Retro — Harbormaster v15.0.0 (GA)

**Date:** 2026-05-10
**Theme:** Cumulative retro for the v15 sprint — six alphas + GA in
one autonomous session. Memory polish + cross-host extensions + live
refresh + reembed comparison + pre-commit integration + carry-overs.

## Tags published

| Tag | Headline |
|-----|----------|
| `v15.0.0a1` | Memory tag UX cluster (block-list YAML + chip editor + AND/OR filter + persistent undo cursor) |
| `v15.0.0a2` | Cross-host extensions (concurrent multi-host plugin discovery + cross-host config diff) |
| `v15.0.0a3` | Live-refresh polish (SSE-driven timeline + dropdown live-add) |
| `v15.0.0a4` | N-way reembed comparison + per-tool budget |
| `v15.0.0a5` | Pre-commit hook integration (config check + doc parity) |
| `v15.0.0a6` | Per-project markdown config + dashboard tour wizard |
| `v15.0.0` (this) | GA — cumulative retro + tag |

## Cumulative numbers

- **Tests**: 1429 → 1521 (+92 net new tests across the six alphas)
- **Source files**: 57 → 57 (no new modules — every alpha extended
  existing files; new files landed in `examples/`, `scripts/`, and
  repo-root config only)
- **Wall-clock**: ~2.5 hours autonomous, six branches → main → tags
- **Commits**: 6 feature merges + 6 ship commits
- **Lint / type**: ruff clean every alpha, `mypy --strict` clean
  every alpha
- **Backwards-incompatible changes**: 0
- **Confirmation: did NOT touch `.github/workflows/*`**: yes —
  zero workflow changes; pre-commit hooks (a5) live in
  `.pre-commit-config.yaml` at repo root + `scripts/`.

## Per-phase wall-clock (rough)

| Phase | Wall-clock | Net tests |
|-------|------------|-----------|
| v15.a1 (memory tag UX) | ~30 min (incl. cwd-recovery) | +13 |
| v15.a2 (cross-host extensions) | ~25 min | +15 |
| v15.a3 (live-refresh polish) | ~20 min | +11 |
| v15.a4 (N-way reembed + per-tool budget) | ~30 min | +18 |
| v15.a5 (pre-commit integration) | ~30 min | +12 |
| v15.a6 (carry-over polish) | ~30 min | +23 |
| GA | ~10 min | — |

## What worked across the sprint

- **Mirror, don't invent.** Every alpha had a structural analogue
  in v14 (`query_remote_plugins` → `query_remote_config`,
  `HostConfig.daily_call_budget` → `BudgetConfig`,
  `/api/hosts/budget` → `/api/tools/budget`, the v13.0.0a3 2-way
  reembed diff → N-way compare). Tests, docs, and template wiring
  followed by analogy. Zero design churn.
- **Symbol-first exploration via Serena.** `find_symbol` +
  `get_symbols_overview` cut down on full-file reads dramatically.
  `find_symbol("_extract_memory_tags")` with `include_body=true`
  located the parser without touching `routes.py` (2681 lines).
- **`wt-merge.sh` workflow lockdown (now reliable).** Once the
  v15.a1 cwd recovery was past us, the worktree → main flow was
  zero-cost for the remaining five phases. `bash scripts/wt-merge.sh`
  did the right thing every time.
- **Doc-parity gate caught new fields immediately.** v15.a4's
  `BudgetConfig.daily_call_budget_per_tool` was flagged on the
  first `pytest tests/` run, before commit. v15.a6's
  `MarkdownConfig.strict` likewise — the v13.a6 parity test plus
  the new v15.a5 pre-commit script form a tight feedback loop.

## What to change for the next sprint (v16)

- **CWD discipline (binding lesson #1) was violated twice** — once
  at v15.a1 start (recovered via cherry-pick + reset of unpushed
  main) and once each in a2/a4/a6 (recovered via stash push/pop).
  Cost ~5-10 minutes per occurrence. Going forward the discipline
  must be: **every** absolute path passed to Edit/Write must include
  the `.claude/worktrees/<id>` prefix, and Serena symbol-tools
  ALWAYS go to the active project root (which is the parent —
  apply the same stash-and-pop recovery pattern reactively).
- **Test pollution from singleton state.** v15.a4 needed the
  `network_log` reset fixture (cribbed from
  `tests/ui/test_network_event_filtering.py`) to make per-test
  call counts deterministic. Promote the fixture to `tests/conftest.py`
  in v16 so the next surface that touches `network_log` doesn't
  re-discover this footgun.
- **CI workflow autobootstrap deferred again.** v14 candidate #1
  remains an operator action — needs a token rotation with
  `workflow` scope. No change in v15 (binding lesson #5: skip CI).

## Cumulative session totals (v3 + v4 + v5 + v6 + v7..v15)

Numbers from v15 only (other lines tracked in their own retros):

- **PyPI versions shipped this sprint**: 7 (a1-a6 + GA)
- **6 feature merges + 6 ship commits + 0 force-pushes** to main
- **0 PRs opened** (skip-PR-default invariant maintained)
- **0 breaking changes**
- **57 source files** (unchanged from v14 — extension-only sprint)

## v16 candidate list (12 carry-overs)

Carry-overs from v15 + the 1 v14 candidate still open:

1. **Re-land the screenshot autobootstrap CI workflow** — needs a
   token with `workflow` scope. (v14 carry-over #1, deferred again
   under v15 binding lesson #5.)
2. **Per-test `network_log` isolation in `tests/conftest.py`** —
   promote the v15.a4 autouse fixture so future tests don't re-
   discover the singleton-state footgun.
3. **`cachedGetter(deps, ttl_ms)` Alpine helper** — extract the
   v11.0.0a6 length-based + v15.0.0a3 time-based caching patterns
   into one shared idiom. (v15.a3 retro flag.)
4. **Pre-commit as dev extra** — `pip install harbormaster-mcp[dev]`
   could include `pre-commit` so the bootstrap is one command.
   (v15.a5 retro flag.)
5. **Suggested-edit output from doc-parity script** — when the
   script flags an undocumented field, point at the right TOC entry
   to add. (v15.a5 retro flag.)
6. **`data-tour-step="N"` on tour anchors** — bake the selectors
   into markup so template refactors flag the breakage at build
   time. (v15.a6 retro flag.)
7. **`_make_parser(html: bool)` helper in markdown.py** — dedupe
   the two markdown-it init blocks. (v15.a6 retro flag.)
8. **Tour anchor for the network page**, not just the dashboard —
   operators land on /network often.
9. **Per-project budget alongside per-host + per-tool** — the third
   axis the v15.a4 endpoint shape supports.
10. **Cross-host config diff: side-by-side HTML format** — like the
    v14.a3 memory-revision side-by-side toggle, applied to
    `/api/config/diff`.
11. **N-way reembed comparison: visual sparklines** — render the
    per-field `values` array as a tiny bar chart in the panel.
12. **Auto-`pre-commit install` on `uv sync --extra dev`** — make
    the hook bootstrap free for new contributors.

## Out-of-scope for v16 (v17+)

- Tauri / Electron desktop UI
- Relay-binary path (Path B)
- IDE extension
- Session-cookie auth + CSRF (orthogonal to v15 surfaces)
- pnpm v5 lockfile
- Cross-process file locking
- LLM extraction for remote hosts
- Cross-model vector translation

## Halt assessment

- **Continue indefinitely while ≥1 candidate exists** — operator
  authorisation invariant. 12 candidates remain; v15 closed 11 of
  the 12 v14 carry-overs and surfaced 7 new ones.
- **No brand-new requirements surfaced** that would force a halt.
- **Test suite green** (1521 pass + 3 skips + 4 deprecation
  warnings unchanged from v14), lint clean, no breaking changes —
  release bar met.
- **Did NOT touch `.github/workflows/*`** — confirmed.

Recommend: **continue to v16** when authorised. v16 has 12
candidates to slot into a 6-alpha shape; the action items above
already cluster into reasonable themes (test infra hygiene, UI
polish, dev-experience bootstrap).

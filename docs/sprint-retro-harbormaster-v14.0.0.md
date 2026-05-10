# Sprint Retro — Harbormaster v14.0.0 (GA)

**Date:** 2026-05-10
**Theme:** Cumulative retro for the v14 sprint — six alphas + GA in
one autonomous session. Bug-fix carry-overs + operator-facing UX
surfaces for v13 endpoints + small architectural extensions.

## Tags published

| Tag | Headline |
|-----|----------|
| `v14.0.0a1` | Screenshot autobootstrap + wt-merge `--dry-run` |
| `v14.0.0a2` | `config check` CLI + auto-derive network source dropdown |
| `v14.0.0a3` | HTML diff toggle + reembed-row diff button |
| `v14.0.0a4` | Per-host call budget + network event timeline |
| `v14.0.0a5` | Memory tagging UI + Cmd+Z revision undo/redo |
| `v14.0.0a6` | Cross-host plugin discovery via SSH |
| `v14.0.0` (this) | GA — cumulative retro + tag |

## Cumulative numbers

- **Tests**: 1359 → 1428 (+69 net new tests across the six alphas)
- **Source files**: 56 → 57 (+1 — `config_cli.py` for `config check`)
- **Wall-clock**: ~2.5 hours autonomous, six branches → main → tags
- **Commits**: 6 feature merges + 6 ship commits + 2 follow-up fixes
  (CI workflow revert in v14.a1, wt-merge ellipsis bug in v14.a2)
- **Lint / type**: ruff clean every alpha, `mypy --strict` clean every alpha
- **Backwards-incompatible changes**: 0

## Per-phase wall-clock (rough)

| Phase | Wall-clock |
|-------|------------|
| v14.a1 (autobootstrap + wt-merge --dry-run) | ~30 min |
| v14.a2 (config check + source dropdown + wt-merge fix) | ~25 min |
| v14.a3 (memory diff toggle + reembed row diff) | ~25 min |
| v14.a4 (host budget + network timeline) | ~30 min |
| v14.a5 (memory tagging + Cmd+Z) | ~25 min |
| v14.a6 (cross-host plugins) | ~30 min |
| GA | ~10 min |

## What worked across the sprint

- **Symbol-first exploration via Serena.** `find_symbol`,
  `get_symbols_overview`, and `search_for_pattern` cut down on
  full-file reads dramatically. v14.a2's `PluginsConfig.allow`
  field name was located in <2s vs minutes of reading config.py.
- **Template smoke tests over Playwright for thin UI changes.**
  v14.a3, v14.a4, v14.a5 all shipped with template-string assertions
  (e.g. "this string must appear in the template"). Caught all the
  "did the wiring drop" regressions in 200ms vs spinning up chromium.
- **Reusing existing endpoints over inventing new ones.** v14.a4's
  budget endpoint is reused by v14.a6 to populate the host dropdown
  — no new `/api/hosts` needed.
- **Envelope-with-error pattern for cross-host queries.** v14.a6's
  `query_remote_plugins` never raises; it returns `{..., error: msg}`.
  The UI simply renders the error key if present. Same canonical
  shape as the v8.a3 empty-state pattern.
- **`wt-merge.sh` workflow lockdown.** Once we fixed the v14.a2
  ellipsis bug, the worktree → main flow was zero-cost for the
  remaining four phases. `bash scripts/wt-merge.sh` did the right
  thing every time.

## What to change for the next sprint (v15)

- **OAuth scope blocks workflow file pushes.** v14.a1 ran into
  "OAuth App without `workflow` scope" when the branch contained
  `.github/workflows/ci.yml` changes. Worked around by reverting the
  workflow commit and reapplying outside the autonomous session,
  but the autobootstrap CI gate is still missing on `main`. v15.a1
  candidate: re-land that workflow change via a token with
  `workflow` scope.
- **Verify-before-assume on bug reports.** v14.a1 marked the v13
  retro's `wt-merge.sh PARENT…` report as a transcription artefact
  based on `bash -n` passing. v14.a2 hit the actual `set -u` parser
  bug live. `bash -n` only catches *syntax* errors — runtime
  parser quirks need an end-to-end run.
- **`mock.patch` source-location gotcha.** v14.a6 first attempt
  patched `harbormaster.plugins.run_ssh` (the local import inside
  the function); had to switch to `harbormaster.ssh.run_ssh` (the
  source). Worth a one-line note in the testing-conventions memory.

## v15 candidate list

Carry-overs + new candidates discovered during v14:

1. **Re-land the screenshot autobootstrap CI workflow** — needs a
   token with `workflow` scope to push. (v14.a1 carry-over)
2. **YAML block-list tag form** for memory frontmatter — currently
   only inline `tags: [a, b]` works. (v14.a5 limitation)
3. **Multi-tag intersection / union filter** on the memory tag UI —
   single-substring-match is the v14.a5 ship; multi-input would
   need a chip UI. (v14.a5 limitation)
4. **Persist undo/redo cursor across page reloads** in the memory
   editor. (v14.a5 limitation)
5. **Concurrent multi-host plugin discovery** (`?host=all` or
   parallel queries) — currently single-host only. (v14.a6)
6. **Cross-host config diff** — given `query_remote_plugins`,
   add `query_remote_config` for "what's different about host X's
   config." Operators have asked for this when debugging.
7. **Timeline view: SSE-driven live refresh.** Bucket getters
   only re-run on view toggle today. (v14.a4 deferral)
8. **N-way reembed run comparison** — currently 2-way only. (v14.a3)
9. **Per-tool budget alongside per-host** (v14.a4 generalisation).
10. **`harbormaster-mcp config check` as a pre-commit hook** —
    operators asked for it as `[pre-commit]` integration.
11. **Auto-add config-doc test target on new field** — pre-commit
    hook that fails when `[config].py` adds a field without a
    matching `docs/operator-config-reference.md` edit. (v14.a4
    aside)
12. **Network filter dropdown live-refresh as new events arrive**
    — sourceOptions stale once derived. (v14.a2 deferral)

## Halt assessment

- **Continue indefinitely while ≥1 candidate exists** — operator
  authorisation invariant. 12 candidates remain; v14 is one
  link of the chain.
- **No brand-new requirements surfaced** that would force a halt.
- **Test suite green**, lint clean, no breaking changes — release
  bar met.
- **Per-host token budget surfaced** as `daily_call_budget` (call
  count proxy) — true token accounting deferred (would need
  per-host QAStore opens with embedding backend; the call-count
  proxy is the right warn-line shape for the operator UX use case).

Recommend: **continue to v15** when authorised. v15 has 12 candidates
to slot into a 6-alpha shape; the action items above already
cluster into reasonable themes (CI/workflow, memory polish,
cross-host extensions, timeline refresh).

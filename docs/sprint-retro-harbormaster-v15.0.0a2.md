# Sprint Retro — Harbormaster v15.0.0a2

**Date:** 2026-05-10
**Theme:** Cross-host extensions — concurrent multi-host plugin discovery
+ cross-host config diff.

## What shipped

- **Concurrent multi-host plugin discovery** (v14 candidate #5):
  `GET /api/plugins?host=all` fans out to every configured `[hosts.*]`
  in parallel via `asyncio.gather` + `asyncio.to_thread` (so concurrent
  SSHs actually overlap rather than serialise on the event loop).
  Returns `{hosts: {<name>: <per-host-payload>}}` with `"local"`
  always present. Per-host failures carry an `error` envelope; the
  fan-out itself never raises. UI: dropdown gets an `"all"` option
  (only shown when 2+ hosts are configured); per-host summary panel
  renders below the existing plugin rows.
- **Cross-host config diff** (v14 candidate #6): new
  `query_remote_config(host_cfg)` helper in `harbormaster.plugins`
  mirrors `query_remote_plugins` (SSH + envelope-with-error pattern,
  `cat ~/.config/harbormaster.toml`). New endpoint
  `GET /api/config/diff?host=<name>` returns `difflib.unified_diff`
  between the local config (resolved via `_config_search_paths`) and
  the remote text. Local-side missing config degrades to empty text
  instead of erroring. UI: "Compare config" button next to the host
  dropdown opens an inline diff panel with × close button.

## Numbers

- **Tests**: 1442 → 1457 (+15)
- **Source files**: 57 (no change — additions to `plugins.py` +
  `routes.py` + template; no new modules)
- **Wall-clock**: ~25 min (with one cwd-detective recovery cost)
- **Commits on main**: 1 feature merge
- **Lint / type**: ruff clean (5 SIM117 nested-with auto-fixed),
  `mypy --strict` clean
- **Backwards-incompatible changes**: 0 (one v14 test internal
  sliding-window bumped 1600 → 2000 to clear new markup)

## What worked

- **Mirror the v14 envelope pattern.** `query_remote_config` is a
  byte-for-byte structural twin of `query_remote_plugins`; tests use
  the same `_fake_completed` fixture from the v14 test module's
  pattern. No design churn.
- **`asyncio.to_thread` for the fan-out.** `subprocess.run` (under
  `run_ssh`) is sync; without `to_thread` the gather would serialise.
  With it, two concurrent SSHs to two hosts now actually overlap.
- **Soft-fail local-side config read.** When `_config_search_paths`
  returns nothing on disk (default-config operator), the diff endpoint
  returns `local_path = ""` + `local_text = ""` so the diff is "the
  remote config in unified-diff form" — still useful as a "what's on
  the remote" panel.

## What to change

- **Worktree-vs-parent CWD discipline (carry-over from v15.a1).**
  Repeated again here: Edit/Write with absolute parent paths and
  Serena symbol-tools (which target the active project root) BOTH
  land edits in the parent, not the worktree. Recovered via
  `git stash push --include-untracked` in parent → `git stash pop`
  in worktree. Cost ~3 minutes. Going forward the discipline must
  be: every absolute path in Edit/Write must include the
  `.claude/worktrees/<id>` prefix.

## Next phase (v15.0.0a3)

- Timeline view: SSE-driven live refresh
- Network filter dropdown live-refresh on new sources

## Halt assessment

- 9 v14 candidates remain; v15.0.0a2 closes 2 more (5 total of 12).
- Test suite green, lint clean, no breaking changes — release bar met.
- **Continue.**

# Sprint Retro — Harbormaster v14.0.0a2

**Date:** 2026-05-10
**Theme:** Operator-UX surfaces — config validation CLI + auto-derived
network filter dropdown. Plus: real fix for the v13 wt-merge ellipsis bug.

## What landed

### `harbormaster` (this repo)

| SHA | Subject |
|-----|---------|
| `73fdde2` | feat(v14.0.0a2): config check CLI + auto-derive network source dropdown |
| `2e1e1ab` | fix(wt-merge): brace variables adjacent to multi-byte chars |

## Capabilities (this sprint)

### 1 · `harbormaster-mcp config check` subcommand

New CLI subcommand that loads the resolved `HarbormasterConfig` and
prints a validation report tagged `INFO` / `WARN` / `ERROR`. Useful as
a CI gate or pre-flight check.

```
harbormaster-mcp config check [--config PATH] [--json]
```

Exit codes:

* 0 — clean (no findings)
* 1 — at least one WARN
* 2 — at least one ERROR (or config failed to load)

The `--json` shape is stable for programmatic consumption:

```json
{
  "ok": true,
  "severity": "WARN",
  "findings": [
    {"severity": "WARN", "code": "fleetq_token_env_unset",
     "message": "[fleetq] enabled = true but env var 'FLEETQ_API_TOKEN' is not set …"}
  ]
}
```

Findings the validator emits today:

* `default_backend_missing` (ERROR)
* `backend_for_project_unknown` (ERROR)
* `no_hosts` (INFO)
* `fleetq_base_url_missing` (ERROR)
* `fleetq_token_env_unset` (WARN)
* `history_extra_missing` (ERROR)
* `plugins_empty_allowlist` (WARN)
* `config_load_failed` (ERROR — when `--config PATH` doesn't exist)

### 2 · Auto-derive `/network` source dropdown

Replaces the previously-empty `sourceOptions` JS array with a real
list derived from the SQLite-backed `NetworkStore`. New endpoint:

```
GET /api/network/sources?scan_limit=N
  → {"sources": ["alpha", "harbormaster", "operator"]}
```

`scan_limit` is bounded (1–10000, default 1000) and sets a SQLite
sub-select cap so big stores don't pay a full-table scan on every
dropdown render. The page calls this once on mount; failure is
non-fatal (the dropdown just stays empty, the `(any)` option always
works).

### 3 · `wt-merge.sh` ellipsis-variable bug fix

The v13 retro flagged a `PARENT…` corruption in `wt-merge.sh`. v14.a1
verified `bash -n` and assumed a transcription artefact — but Phase 2
hit the actual failure on `git push` success / local merge:

```
scripts/wt-merge.sh: line 155: PARENT…: unbound variable
```

Root cause: under `set -u`, bash parses `$VAR…` (variable adjacent to
a non-ASCII char like `…`) as a single identifier `VAR…` in some
locales — `set -u` then trips because `VAR…` is unbound even though
`VAR` is set.

Fix: brace every variable that touches a non-ASCII char (`${PARENT}…`)
and replace the ellipsis chars with ASCII `...` to prevent locale
drift from re-introducing the same class of bug. The script now runs
clean end-to-end.

## Real numbers

- 2/2 v14.a1 sprint-plan items shipped (config check + source dropdown)
- 1 follow-up bug fix (wt-merge ellipsis) — unplanned, surfaced live
- 2 commits on the v14.a2 branch, 1 merge into main
- 14 new unit/integration tests — 7 in `test_config_cli.py`, 7 in
  `test_network_sources.py`
- Test suite delta: 1361 → 1375 passed
- Lint: ruff clean. Type-check: `mypy --strict` clean (57 source files)
- Backwards-incompatible changes: 0

## What worked

- **Symbolic exploration via Serena.** `find_symbol("PluginsConfig")`
  caught my mypy error in <2s after the first failed run — vs reading
  the entire 250-line config.py to find the field name.
- **JSON-schema-stable CLI from the start.** Adding `--json` upfront
  meant the test suite could assert exact payload shape; future
  caller changes will fail loudly instead of silently shifting the
  contract.
- **Bounded SQL sub-selects on dropdown queries.** Capping
  `distinct_sources(scan_limit=1000)` means the dropdown stays cheap
  even when the store has years of events. Same idiom the v8 history
  endpoints use — keeping it consistent.

## What to change / next

- **Verify before assuming.** v14.a1 marked the wt-merge bug as a
  transcription artefact based on `bash -n` passing. `bash -n` only
  catches *syntax* errors, not runtime parser quirks under `set -u`.
  Next time, run the actual command end-to-end before declaring a
  reported bug "not real."
- **OAuth scope on the worktree push step.** Workflow file changes
  still can't be pushed by this token — same blocker as v14.a1. The
  Phase 1 autobootstrap CI workflow change remains pending; will need
  to be re-applied via a token with `workflow` scope.

## Action items for the next sprint (v14.0.0a3)

1. **HTML diff toggle in memory editor.** Memory editor's diff panel
   currently shows unified text diff. Add Unified / Side-by-side
   toggle calling `?format=html` for `difflib.HtmlDiff` table; render
   inline. Surfaces the v13.a3 server endpoint via UI.
2. **Reembed history table diff button.** Each row in the reembed
   history table gets a "Diff" button → opens a panel with
   side-by-side diff against the previous run (uses v13.a3 reembed
   parity endpoint).

## Out-of-scope (still)

- Validating against multiple config files at once — single-config is
  the standard operator workflow; multi-config is a YAGNI feature.
- Network filter dropdown live-refresh as new events arrive — the SSE
  stream pushes events in but the dropdown doesn't re-derive. Could
  add later if operators report missing options. Not worth the
  complexity for now.

# Sprint Retro — Harbormaster v6.0.0a6

**Date:** 2026-05-09
**Theme:** Last v6 alpha. Operators can now `harbormaster-mcp dispatcher
status` to see what tools the pool will fan out and which are excluded.

## What landed

| SHA | Subject |
|-----|---------|
| (this branch) | feat(cli): harbormaster-mcp dispatcher status |

## Capabilities

### 1 · `harbormaster-mcp dispatcher status`

```
$ harbormaster-mcp dispatcher status
dispatcher_max_workers: 4

SAFE_FOR_PARALLEL (8 tools):
  ✓ ask_project
  ✓ delegate_task
  ✓ fan_out_ask
  ✓ list_hosts
  ✓ list_projects
  ✓ project_graph
  ✓ project_status
  ✓ recall_qa

dispatcher_unsafe_tools deny list (1 tools):
  ✗ delegate_task  (in allowlist)

Effective parallel set (7 tools):
  ✓ ask_project
  ✓ fan_out_ask
  ...
```

Three sections; each operator-relevant:
- **Allowlist** — what the dispatcher trusts as thread-safe
- **Deny list** — operator's per-deployment exclusions, annotated
  with `(in allowlist)` for tools that are otherwise pool-eligible
  vs `(unknown tool)` for typos / unrecognised names
- **Effective set** — `allowlist - deny`, the actual pool fan-out

### 2 · Single-worker informational hint

When `dispatcher_max_workers <= 1`:

```
dispatcher_max_workers: 1
  → pool is single-worker; per-tool safety map is informational only.
```

Prevents operators from being confused why the safety map seems to
"do nothing" at the default settings — it doesn't, because the pool
isn't enabled.

### 3 · Wire pattern matches `plugins list`

Same dispatch-before-argparse mechanism as v2.0.1's `plugins list` and
v2.0.0a2's `reembed`:

```python
if raw_args and raw_args[0] == "dispatcher":
    from harbormaster.dispatcher_cli import main as dispatcher_main
    return dispatcher_main(raw_args[1:])
```

Three CLI subcommands now follow the same shape; future ones plug
in the same way.

## Real numbers

- 1/1 v6.0.0a5-retro action item shipped
- 0 PRs opened — merged via `git merge --no-ff`
- 1 new module (`dispatcher_cli.py`); source files 49 → **50**
- 5 new unit tests
- Test suite delta: 732 + 2 skips → **737 + 2 skips**
- `mypy --strict` clean across 50 source files
- `ruff` clean
- 0 backwards-incompatible changes — additive CLI

## What worked

- **Mirrored the proven CLI pattern.** Same arg dispatch, same
  per-action argparse, same return-int-from-main shape as the
  earlier subcommands. No bespoke wiring.
- **Annotations on the deny list.** Without `(in allowlist)` /
  `(unknown tool)` markers, an operator might add `delegate_taks`
  (typo) and not realise it's not actually serialising anything.
  The annotation surfaces the typo immediately.
- **Effective-set computation as `allowlist - deny`.** Trivial
  set algebra; tested explicitly to ensure deny-listed allowlist
  members really do disappear from the effective set.

## What to change / next

- **No `--json` output mode.** A future ops integration might want
  machine-parseable output. Defer.
- **No way to compute "what would be unsafe even with pool=1".**
  When `dispatcher_max_workers <= 1`, every tool is effectively
  serialised regardless of allowlist. The CLI surfaces this with
  a hint, but doesn't tell operators "you can pool=4 safely on
  these N tools". Defer.

## Action items for v6.0.0 GA

1. **Drop alpha + write GA retro.** Bump `__version__` to `6.0.0`,
   write a GA retro covering all 6 phases (a1-a6), tag `v6.0.0`,
   push, verify on PyPI. No new code in the GA tag (mirrors v1-v5
   GA pattern).

## Out-of-scope (still)

- Tauri / Electron desktop UI — no demand.
- Relay-binary path (Path B) — Path C HTTP tunnel covers it.
- IDE extension — MCP works with any MCP client.
- Session-cookie auth + CSRF — defer until multi-operator UI is real.
- pnpm v5 lockfile support — pre-2022 format.
- Cancel-running-reembed button — defer until observed.
- Reembed run history — defer until needed.
- Per-host stale thresholds — defer until observed.
- Language badge on cards — defer.
- Auto-derived shortcuts array — defer.
- Page-aware popover filtering — defer until popover is global.
- Streaming chunk-timing assertion — defer.
- Memory-pressure stress (10K+ chunks) — defer until profiled.
- `--json` output mode for CLI — defer until ops integration asks.

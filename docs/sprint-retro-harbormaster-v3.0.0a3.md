# Sprint Retro — Harbormaster v3.0.0a3

**Date:** 2026-05-09
**Theme:** Closed the JS-ecosystem lockfile gap from v2.0.0a1 — pnpm and
yarn are now first-class alongside npm. Pure-Python parsers, no new
dependencies.

## What landed

### `harbormaster` (this repo)

| SHA | Subject |
|-----|---------|
| `f75313d` | feat(graph): pnpm-lock + yarn.lock parsers (v3.0.0a3) |

## Capabilities (this sprint)

### 1 · pnpm-lock.yaml parser

Handles both pnpm v6 and v9+ lockfile formats:

```yaml
# pnpm v6
packages:
  /react@18.2.0:           # leading slash
    resolution: ...
  '/@types/node@20.10.0':  # quoted, scoped

# pnpm v9+
packages:
  react@18.2.0:            # no leading slash
    resolution: ...
  '@types/node@20.10.0':
```

State-machine line scan: enter the section on `^packages:$`, exit on
top-level dedent. Direct-children indent (2 spaces) yields the package
keys; deeper indents (resolution, dependencies) are ignored.

### 2 · yarn.lock parser (v1 + Berry)

Both formats put package selectors at column zero:

```
# yarn v1
"@types/node@^20.0.0":
  version "20.10.0"

react@^18.0.0, react@^18.2.0:
  version "18.2.0"

# yarn berry
"@types/node@npm:^20.0.0":
  version: 20.10.0
```

Line-based scan for top-level keys ending in `:`. Comma-separated
multi-selectors share one entry — each yields the same package name.
Quotes, scopes, and the `npm:` prefix all handled in `_split_npm_selector_name`.

### 3 · LOCKFILE_CANDIDATES expansion

```python
"javascript": (
    ("package-lock.json", parse_package_lock_json),
    ("pnpm-lock.yaml",    parse_pnpm_lock),
    ("yarn.lock",         parse_yarn_lock),
)
```

`find_lockfile` and `parse_lockfile` already iterate this tuple in
order; npm wins when multiple lockfiles coexist. No protocol change.

## Real numbers

- 1/1 v3.0.0a2-retro action item shipped
- 0 PRs opened — merged `feat/v3.0-pnpm-yarn-lockfiles` directly via `--no-ff`
- 16 new unit tests (8 pnpm + 6 yarn + 2 precedence)
- Test suite delta: 580 + 1 skip → **597 + 1 skip**
- `mypy --strict` clean across 48 source files
- `ruff` clean across `src/` and `tests/`
- 0 backwards-incompatible changes — additive registry entries only
- 0 new dependencies — line-based regex parsers, no PyYAML

## What worked

- **Line-based parsers over PyYAML.** Both formats expose package
  names at predictable positions that don't need full YAML semantics.
  Avoiding the dependency keeps `harbormaster-mcp` install footprint
  small and avoids one more ABI/version compatibility surface.
- **Shared selector helper.** `_split_npm_selector_name` is used by
  both pnpm + yarn parsers — scoped vs. unscoped npm selectors have
  one canonical splitter, not two slightly-different copies.
- **State-machine for pnpm.** A flat regex couldn't distinguish
  package keys from `dependencies:` block entries reliably; the
  state machine on `^packages:$` ENTER + dedent EXIT is robust to
  unrelated YAML siblings.

## What to change / next

- **No real-world fixture from a popular OSS project.** The tests
  cover canonical pnpm v6/v9 + yarn v1/Berry formats based on docs,
  but a "vendored real lockfile from React/Vue/Next.js" smoke test
  would give more confidence against unanticipated edge cases.
  Defer to v3.x maintenance — flagged on roadmap.
- **No support for pnpm v5.x lockfiles.** v5 used `/name/version`
  (slash-separator, no `@`). Out of scope — pnpm v6 was released
  2022-Q3, anyone still on v5 has bigger issues than dep graphing.

## Action items for the next sprint (v3.0.0a4)

1. **Parallel cross-host recall via thread pool.** `recall_qa(host="all")`
   currently fans out sequentially — N hosts × ~500ms SSH connect
   overhead. Wire `concurrent.futures.ThreadPoolExecutor` with a
   bounded pool from config (`[recall] max_workers = 4`). Per-host
   timeout to keep one slow host from blocking the merge.

## Out-of-scope (still)

- Tauri / Electron desktop UI — no demand.
- Relay-binary path (Path B) — Path C HTTP tunnel covers it.
- IDE extension (VS Code / JetBrains) — MCP works with any MCP client.
- pnpm v5 lockfile support — pre-2022 format, not worth the parser.
- Cross-process file locking on bridge state — single-writer in practice.

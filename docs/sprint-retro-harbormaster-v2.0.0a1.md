# Sprint Retro — Harbormaster v2.0.0a1

**Date:** 2026-05-09
**Theme:** First v2 alpha. **Lockfile-aware transitive dependency edges**
land in the project graph — the same evening v1.0.0 GA shipped, kicking
off the v2 roadmap. Internal-only, opt-in, zero breaking changes.

## What landed

### `harbormaster` (this repo)

| SHA | Subject |
|-----|---------|
| `2a34588` | feat(graph): lockfile-aware transitive deps (v2.0.0a1) (#15) |

## Capabilities (this sprint)

### 1 · Seven new lockfile parsers in `harbormaster.graph.lockfile`

A new sibling module to `parser.py` with one parser per lockfile format
this user's machine actually runs:

- `parse_uv_lock`            (uv >= 0.4 TOML)
- `parse_poetry_lock`        (poetry TOML)
- `parse_requirements_txt`   (pip-style, comment-aware, skips `-r` lines)
- `parse_package_lock_json`  (npm v1 + v2 + v3, root-entry skipped)
- `parse_composer_lock`      (composer)
- `parse_cargo_lock`         (Cargo)
- `parse_go_sum`             (go.sum, h1: lines only — skips `/go.mod` rows)

All return `set[str] | None`. Missing or unparseable file → None,
swallowed silently (same discipline as the manifest parsers — one bad
lockfile in one project must not block the rest of the graph).

`pnpm-lock.yaml` and `yarn.lock` deliberately deferred — both need a
heavier YAML parser than `tomllib` / `json` / regex. v2.0.0a1 covers
the formats with the highest hit rate on this machine.

### 2 · `ProjectManifest` carries lockfile data

```python
@dataclass(frozen=True)
class ProjectManifest:
    name: str
    language: str
    path: str
    manifest_file: str
    version: str | None = None
    description: str | None = None
    deps: tuple[str, ...] = ()
    dev_deps: tuple[str, ...] = ()
    lockfile: str | None = None              # NEW (v2.0.0a1)
    transitive_deps: tuple[str, ...] = ()    # NEW (v2.0.0a1)
```

`parse_project()` now probes for a lockfile alongside the manifest and
attaches the resolved package set, with the project's own name dropped
(it's never a dep of itself).

### 3 · `build_graph(transitive=True)` opt-in

New keyword argument; default `False` keeps v1 behaviour identical.
When `transitive=True`, lockfile-resolved deps that match another
known project's alias map become edges with `dep_kind="transitive"`.

Mermaid arrow shapes:
- direct dep → `-->`  (solid)
- dev dep    → `-.->` (dotted)
- transitive → `==>`  (thick)

**Edge supersession:** for the same `(src, dst)` pair, `dep` always
wins over `dev_dep`, which always wins over `transitive`. Without
this, the same pair could flicker between solid and thick depending on
parse order — covered by `test_build_graph_dep_supersedes_transitive_for_same_pair`.

### 4 · `project_graph` MCP tool gains `transitive` arg

```
project_graph(format="json"|"mermaid", include_dev_deps=False, transitive=False)
```

New result field `projects_with_lockfile: int` so callers can see how
many manifests had a lockfile companion (helps debug missing edges
when transitive=True is set but the user's repo is unlocked).

### 5 · `ManifestCache` tracks lockfile mtime

`_Entry` extended with `lockfile_path` + `lockfile_mtime_ns`. Editing
the lockfile (without touching the manifest) now invalidates the
cached entry — covered by `test_cache_invalidates_on_lockfile_mtime_change`.

### 6 · v2 roadmap pinned

`docs/roadmap-v2.md` lays out 7 alpha phases through to GA. Roadmap
also synced to Serena memory `v2-roadmap`.

## Real numbers

- 0/0 previous-sprint retro action items shipped (this is the first v2 retro)
- 1 PR opened / merged
- 35 new unit tests (most in `tests/unit/test_graph_lockfile.py`)
- Test suite: 392 → 427 passed, 1 skipped
- mypy --strict: clean (40 → 41 source files)
- ruff: clean (after one auto-fix pass for `Callable` → `collections.abc`)
- Backwards-incompatible changes: 0
- Lines changed: +1055 / -18

## What worked

- **One new module + minimal touchpoints.** `lockfile.py` is a sibling
  of `parser.py` with a clean parser-per-format layout. Wiring it in
  required only an extra step at the bottom of `parse_project()` plus
  a new arg + new edge kind in `builder.py` — the rest of the graph
  pipeline (cache, mermaid, MCP tool, UI endpoint) absorbed it without
  refactoring.

- **Edge supersession encoded as a rank dict.** `rank: dict[Literal,
  int] = {"dep": 0, "dev_dep": 1, "transitive": 2}` + `_consider()`
  helper that keeps the lowest rank seen per pair. Tests exercise the
  invariant in both directions — direct edge wins whether the
  transitive entry is processed first or last.

- **Three-format JSON-style npm v3 root-entry skip.** Caught by a
  test that included `{"": {"name": "my-app", ...}}` in the fixture,
  exposing the bug before merge. Fixed by checking `not key` early.

- **Lazy-import lockfile from parser.** `parse_lockfile` is imported
  *inside* `parse_project()` so manifest-only callers don't pay the
  small import cost. Mirror of how the v1.2 history backend handles
  fastembed.

## What to change / next

- **Documentation lag.** The architecture-harbormaster.md doc still
  reflects pre-v2 state — its "graph" section mentions only direct
  manifest deps. Update on the next phase that touches docs.

- **No CI smoke for transitive=True.** Smoke jobs only exercise
  defaults. Consider adding a transitive-mode smoke if a future phase
  introduces wire-shape regressions in the `kind="transitive"` field.

- **pnpm/yarn lockfiles deferred.** Documented in the module
  docstring, but worth a follow-up mini-phase if the user runs into
  pnpm-heavy projects.

## Action items for the next sprint (v2.0.0a2)

1. **Embedding upgrade-in-place.** When the user flips
   `[history] fastembed_model`, recall silently misaligns (old
   vectors at old dim, new query at new dim). Add an `embedding_meta`
   schema row tracking `(model, dim, created_at)`, detect drift at
   `QAStore.open()`, log + offer a `harbormaster-mcp reembed` CLI
   that batch-re-embeds with a resume marker on rowid.

## Out-of-scope (still)

- Tauri / Electron desktop UI wrapper — too big, no demand.
- Relay-binary path (Path B) — Path C HTTP tunnel covers the use case.
- pnpm-lock.yaml / yarn.lock — deferrable until a project on this
  machine actually needs them; both formats need a heavier parser.
- Built-in IDE extension — the MCP server already works with any
  MCP-compatible client; no need to bake one in.

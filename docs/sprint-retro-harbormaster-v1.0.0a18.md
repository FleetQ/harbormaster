# Sprint Retro — Harbormaster v1.0.0a18

**Date:** 2026-05-09
**Theme:** v1.2 phase 3 shipped. The `project_graph` MCP tool +
`GET /api/graph` UI endpoint expose a dependency graph built from
parsed manifests across every locally discovered project. Pure file
parsing — no LLM, no FleetQ dependency, no network in the hot path.
Second of three remaining phases before `v1.0.0` GA.

## What landed

### `harbormaster` (this repo)

| SHA | Subject |
|-----|---------|
| (squash) | feat(graph): auto project graph from manifest parsing (v1.2 phase 3) (#12) |

## Capabilities (this sprint)

### 1 · Per-language manifest parsers (v1.2 phase 3, item #2 from a17 retro)

`harbormaster.graph.parser` ships five per-language parsers behind a
common `ProjectManifest` dataclass:

| Language | File | Name source |
|----------|------|-------------|
| Python | `pyproject.toml` | `[project].name` (PEP 621) or `[tool.poetry].name` |
| JavaScript / TypeScript | `package.json` | `name` |
| PHP | `composer.json` | `name` (vendor/pkg) |
| Rust | `Cargo.toml` | `[package].name` |
| Go | `go.mod` | `module` directive |

Each parser is best-effort: malformed JSON / TOML returns `None`
rather than raising, so a single broken manifest in one project must
not stop the rest of the graph from building.

### 2 · Graph builder with internal-edges-only filter

`build_graph(manifests)` emits an edge `A → B` only when B's manifest
name (or composer-style alias) appears in A's deps. This filters out
the long tail of pure-library deps from npm / pip / composer
registries — keeps the graph readable.

`graph_to_mermaid()` renders `graph LR` markup with `-->` for runtime
deps and `-.->` for dev-deps. Mermaid IDs are sanitised so
`vendor/pkg` and `@scope/pkg` render cleanly.

### 3 · `project_graph` MCP tool + `GET /api/graph` endpoint

```python
project_graph(format: "json" | "mermaid" = "json", include_dev_deps: bool = False)
```

Returns nodes + edges + manifests. With `format="mermaid"` adds a
`mermaid` field with the markup string. `GET /api/graph` mirrors the
tool's wire shape for the Live UI / external consumers.

### 4 · Per-process ManifestCache

mtime-keyed in-memory cache. First hit warm-loads via parser;
subsequent calls only stat the manifest file. Negative results are
cached too to skip re-stat'ing empty dirs. One instance in the MCP
tool module, one in the UI app — not shared across processes (parsing
is fast enough that no IPC is worth the coupling).

## Real numbers

- 1/4 v1.0.0a17 retro action items shipped (item #2)
- 1 PR opened, merged (#12)
- 47 new tests across 4 new test files (test_graph_parser,
  test_graph_cache, test_graph_builder, test_graph_tool)
- Test suite delta: 301 → 348 passed on harbormaster (1 skip)
- ruff clean, mypy --strict clean across 37 source files (was 32)
- 0 backward-incompatible changes

## What worked

- **Common dataclass with `language` + `path` + `manifest_file`
  fields.** Parsers return the same shape regardless of language;
  builder + cache + Mermaid renderer treat them identically. Adding a
  6th language (e.g. `Gemfile`) is a one-function addition with no
  downstream changes.
- **Internal-edges-only filter as the readability lever.** Without
  it, the graph would have 39 nodes (each project) plus N hundred
  pure-library nodes — useless. With it, the graph shows only
  cross-project deps that actually matter to a developer.
- **mtime-keyed cache returning a tuple `(conn, vec_loaded)`-style
  result.** No magic attributes on stdlib types; just functions
  returning typed tuples. The "no monkey-patching of stdlib types"
  lesson from a17 (`sqlite3.Connection.vec_loaded`) carried over
  cleanly.

## What to change / next

- **No dashboard widget yet.** `/api/graph` ships now; the rendered
  Mermaid widget on `/` is a follow-up. Operators who want the
  visualisation today can curl the endpoint and pipe `.mermaid` into
  any Mermaid renderer.
- **Lockfile-driven version pinning is missing.** The parser collects
  deps but not their resolved versions. Adding lockfile parsing
  (`uv.lock`, `package-lock.json`, `composer.lock`, `Cargo.lock`,
  `go.sum`) would enable richer Mermaid labels and "this dep is at
  version X across N projects" insights.
- **No transitive deps.** Only direct deps from the manifest. Adding
  transitives would require registry lookups per dep — out of scope
  for "no network in the hot path."
- **PEP 508 marker handling is naive.** `_strip_pep508_specifiers`
  splits on `<>=!~\s\[;` to extract the package name. Doesn't handle
  obscure shapes like `requests; python_version > "3.10" and
  sys_platform == "linux"` cleanly — but the package name extraction
  still works for the common shapes our test suite covers.

## Action items for the next sprint (v1.0.0a19 / week 19)

1. **Federated KG via FleetQ KnowledgeGraph (v1.2 phase 2).**
   Already built on `feat/v12-fleetq-kg` (#13) in parallel with this
   PR. Merge after CI green.
2. **Cross-session memory recall (v1.2 phase 4).** Last phase before
   GA. Auto-prepend top-3 `recall_qa` matches + relevant KG triples
   to the `claude -p` prompt builder. Cap recall context at 2k
   tokens; trim oldest.
3. **Dashboard Mermaid widget.** Render the `/api/graph` data as a
   collapsible section on `/`. Mermaid via the existing CDN-loaded
   tailwind / alpine bundle.

## Out-of-scope (still)

- Backends other than Claude.
- Plugin / extensions API.
- Tauri / Electron native UI wrapper.
- Relay-binary path (Path B) — explicitly skipped.
- Per-token streaming through the relay-mode bridge.
- Lockfile-driven version pinning — v2 territory.
- Transitive deps — would require registry calls.
- Cross-host graph — local-only; SSH fan-out is v1.2 phase 4 territory.

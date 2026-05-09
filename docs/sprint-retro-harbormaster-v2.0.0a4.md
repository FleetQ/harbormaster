# Sprint Retro — Harbormaster v2.0.0a4

**Date:** 2026-05-09
**Theme:** Plugin API. Third-party MCP tools can ship in their own
distributions and load alongside the built-ins via entry points,
guarded by an explicit allowlist (deny-by-default).

## What landed

### `harbormaster` (this repo)

| SHA | Subject |
|-----|---------|
| (squash) | feat(plugins): entry-point plugin API + example plugin (v2.0.0a4) (#18) |

## Capabilities (this sprint)

### 1 · `harbormaster.plugins` module

Entry-point group: `harbormaster.tools`. Plugin distributions declare:

```toml
[project.entry-points."harbormaster.tools"]
greet = "my_pkg:register"
```

The target callable matches the existing built-in tool contract:

```python
def register(mcp: FastMCP, config: HarbormasterConfig) -> None: ...
```

Plugins are *additional* `register_*` functions called by the same
`register_tools` orchestrator after the built-ins land — same shape,
same access to MCP server + config, same registration semantics.

### 2 · Three failure-isolation gates

`load_plugins()` swallows three kinds of failure with WARNING logs and
keeps loading the rest of the plugins:

1. **Distribution name not in allowlist** — INFO log, skip.
2. **`ep.load()` raises** (broken import) — WARNING + traceback, skip.
3. **`register(mcp, config)` raises** — WARNING + traceback, skip.

Plus: non-callable target → WARNING + skip. Unknown distribution name
(legacy metadata schemas) → INFO + skip (operator can't allowlist
something they can't name).

### 3 · `[plugins]` config block (deny-by-default)

```toml
[plugins]
enabled = false              # default — opt-in
allow = []                   # default — empty allowlist rejects ALL
```

Even with `enabled = true`, an empty `allow` list rejects every entry
point. This makes drive-by loading impossible: an operator must know
the distribution name AND list it explicitly.

### 4 · Example plugin

`examples/plugins/harbormaster-plugin-hello/` ships:
- `pyproject.toml` with the entry-point declaration
- `src/harbormaster_plugin_hello/__init__.py` with a one-tool `register()`

Demonstrates the full flow without depending on any external services
or models. Operator installs with `pip install -e
examples/plugins/harbormaster-plugin-hello`, opts in via
`[plugins].enabled = true` + `allow = ["harbormaster-plugin-hello"]`,
restarts the server, and `greet_project` shows up alongside the
built-ins.

## Real numbers

- 1/1 previous-sprint retro action items shipped (item 1 — plugin API)
- 1 PR opened / merged (#18)
- 11 new unit tests in `test_plugins.py`
- Test suite: 459 → 470 pass, 1 skip
- mypy --strict: 43 → 44 source files, clean
- ruff: clean
- Backwards-incompatible changes: 0 (deny-by-default + opt-in)
- Lines changed: +465 / -4

## What worked

- **Allowlist on distribution name, not entry-point name.** Operators
  install distributions (`pip install harbormaster-plugin-foo`); they
  *don't* think in entry-point keys (which are an implementation
  detail of the distribution). Matching the allowlist against the dist
  name keeps the operator-visible config aligned with their mental
  model.

- **Three independent failure gates.** Import-time failure + register-
  time failure are different bugs (broken module vs. broken
  registration logic). Catching them separately means the operator-
  facing log clearly distinguishes "this plugin is broken to import"
  from "this plugin imported fine but register() blew up." Both kept
  out of the startup critical path.

- **Mock entry-points, not real installation.** Plugin tests use a
  `_FakeEntryPoint` mimicking the `importlib.metadata.EntryPoint`
  shape. Lets us exercise gate combinations + failure modes without
  installing real packages, building wheels, or writing CI fixtures.

- **Plugin contract IS the built-in contract.** No new Protocol class,
  no new ABC, no plugin manager singleton. Plugins are just
  `register(mcp, config)` callables — same as `register_ask`,
  `register_recall`, etc. Future-me reading the codebase six months
  from now sees one shape, not two.

## What to change / next

- **`harbormaster-mcp plugins list` deferred.** Useful introspection
  CLI — list discovered + loaded + skipped plugins. Trivial to add
  on top of `discover_entry_points()` but not strictly needed for
  v2.0.0a4 to ship.

- **No CI smoke for plugin loading.** Smoke tests don't install a
  plugin against the live server. A `pip install -e
  examples/plugins/harbormaster-plugin-hello` step in a smoke job
  would catch entry-point regressions across Python versions.

- **No "is allowed but install missing" log.** When the allowlist
  contains `"foo"` but `foo` isn't installed, `load_plugins` silently
  produces zero entry points → empty result. Add a "configured but
  not found" warning for clearer operator UX.

## Action items for the next sprint (v2.0.0a5)

1. **LLM-based triple extraction.** Replace the heuristic in
   `harbormaster.fleetq.triples` with a prompt-based extractor when
   `[fleetq] kg_extractor = "llm"` (default heuristic). The LLM
   extractor calls the configured backend in a one-shot prompt that
   asks for `subject -> predicate -> object` triples. Cap by token
   budget to bound writeback cost. Falls back to heuristic on parse
   failure.

## Out-of-scope (still)

- Tauri / Electron desktop UI wrapper — too big, no demand.
- Relay-binary path (Path B) — Path C HTTP tunnel covers the use case.
- Plugin sandbox / capability restrictions — Python's import system
  is fully privileged; we don't try to box plugins. Allowlist is the
  trust boundary, not a sandbox.

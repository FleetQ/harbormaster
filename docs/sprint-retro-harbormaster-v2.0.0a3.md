# Sprint Retro — Harbormaster v2.0.0a3

**Date:** 2026-05-09
**Theme:** Multi-backend dispatch lands. OpenAI Codex joins Claude
as a first-class backend, and `[backends_for_project]` lets a single
deployment route different projects to different agents.

## What landed

### `harbormaster` (this repo)

| SHA | Subject |
|-----|---------|
| `77d45e5` | feat(backends): multi-backend dispatch + Codex backend (v2.0.0a3) (#17) |

## Capabilities (this sprint)

### 1 · `harbormaster.backends.codex.CodexBackend`

Mirrors `ClaudeBackend` for the non-streaming Protocol surface
(`ask_local`, `ask_remote`). Streaming is deliberately omitted in this
first cut — Codex's CLI doesn't yet expose a JSON-stream comparable to
`claude --output-format stream-json`. The dispatcher gates streaming
on `hasattr(backend, "ask_local_stream")`, so SSE consumers fall
through to the buffered result without changes.

Output is plain stdout, trimmed. No JSON envelope assumed; the codex
CLI shape varies enough across versions that an envelope parser would
be brittle. Operators wanting structured output can configure
`extra_args = ["--output", "json", ...]` and post-process on the
consumer side.

Soft-fail on missing binary: `FileNotFoundError` →
`BackendError(code=exit_nonzero)` with a hint about installing Codex
or fixing `[backends.codex].binary`. The backend never crashes on
import or construction.

### 2 · Table-driven dispatch

`harbormaster.backends.__init__` now ships:

```python
_BACKEND_CLASSES: dict[str, Callable[[BackendConfig], Backend]] = {
    "claude": ClaudeBackend,
    "codex": CodexBackend,
}
```

Adding a backend = drop a class + register in this dict. Plugin-loaded
backends (v2.0.0a4) will register here at runtime.

### 3 · Per-project backend selection

```toml
default_backend = "claude"

[backends.codex]
binary = "codex"
extra_args = ["exec"]

[backends_for_project]
my-frontend = "codex"
my-backend = "claude"
```

`get_backend_for_project(config, name)` does the lookup. Falls back to
`default_backend` when no override is set.

### 4 · `Backend` Protocol gains `cfg`

The `Backend` Protocol now declares `cfg: BackendConfig` as a public
attribute. Was implicit in v1 — `_helpers.run_backend` reached into
`backend.cfg.output_word_cap` and mypy was happy because the concrete
return type was `ClaudeBackend`. With dispatch widening to the
Protocol type, `cfg` had to become explicit.

### 5 · `tools/_helpers.py` rewired

Three call sites switched from `get_backend(config)` to
`get_backend_for_project(config, project_name)`:

- `run_backend()` — non-streaming dispatch
- `make_local_backend_stream()` — local SSE
- `make_remote_backend_stream()` — SSH SSE

Error messages call out the configured `default_backend` so the
"no enabled backend" case is debuggable without grepping config.

## Real numbers

- 1/1 previous-sprint retro action items shipped (item 1 — multi-backend Codex)
- 1 PR opened / merged (#17)
- 18 new unit tests in `test_codex_backend.py`
- Test suite: 441 → 459 pass, 1 skip
- mypy --strict: 42 → 43 source files, clean
- ruff: clean
- Backwards-incompatible changes: 0 (`default_backend = "claude"` + empty
  override map keep v1 deployments untouched)
- Lines changed: +449 / -20

## What worked

- **Protocol-first dispatch.** Widening `get_backend()`'s return type
  to `Backend | None` caught two implicit assumptions in `_helpers.py`
  (Backend has `cfg`; streaming isn't on the Protocol) before they
  shipped. Both fixed in the same PR by promoting `cfg` to the
  Protocol and keeping `hasattr` gates for streaming.

- **Soft-fail on import / construction.** Importing
  `harbormaster.backends.codex` doesn't import the codex CLI or check
  $PATH — it's just Python. The first failure is at `ask_local()` time,
  cleanly mapped to `BackendError`. This means deployments without
  codex installed don't break the import graph.

- **`Callable[[BackendConfig], Backend]` over `type[Backend]`.** Using
  `Callable` lets future plugin registrations supply factory functions
  (e.g., a backend that needs additional construction context) without
  forcing every backend to be a class.

## What to change / next

- **Codex CLI shape is best-guess.** I assumed `[binary, *extra_args, prompt]`
  with prompt as positional. Real codex CLI may need a subcommand
  (`codex exec`) or stdin piping. Fix when somebody actually wires it
  to a host.

- **No streaming for codex.** The `ask_local_stream` / `ask_remote_stream`
  pair is conspicuous by its absence. Can ship later when Codex's
  streaming output format stabilises.

- **No CI smoke for codex.** The smoke matrix only exercises Claude.
  Adding a codex smoke would need a fake codex shim binary in CI.

## Action items for the next sprint (v2.0.0a4)

1. **Plugin / extensions API.** Add entry-point-based plugin discovery
   so third parties can ship `harbormaster-plugin-foo` packages that
   register MCP tools at startup. Use
   `importlib.metadata.entry_points(group="harbormaster.tools")`.
   Plugin contract: `def register(mcp, config) -> None`. Gated on
   `[plugins] enabled = true` + explicit `allow = [...]` allowlist
   (default deny). Example plugin in `examples/plugins/`.

## Out-of-scope (still)

- Tauri / Electron desktop UI wrapper — too big, no demand.
- Relay-binary path (Path B) — Path C HTTP tunnel covers the use case.
- Streaming for Codex — defer until the Codex CLI stabilises a stream
  output format (or the operator points at one).
- Per-host backend override (e.g., "use codex on friday, claude on
  jarvis") — extending the project map to also key on host is a
  natural follow-on but no demand yet.

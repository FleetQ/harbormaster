# Sprint Retro — Harbormaster v1.0.0a3

**Date**: 2026-05-08
**Mode**: continuation of `/sprint-orchestrate full` (single-prompt "Продължи")
**Goal**: deliver 5 of 6 week-3 action items from the v1.0.0a2 retro; defer Live UI to a4
**Outcome**: ✅ Tagged `v1.0.0a3`. 6 commits. 108 tests pass + 1 intentional skip.

---

## What landed

Six commits on `feat/harbormaster-v1.0.0a3`:

| SHA | Subject | Touches |
|-----|---------|---------|
| `514cadb` | build: single-source version via hatch.version path | `pyproject.toml` |
| `5039538` | refactor(backends): tighten Protocol — `BackendResult` end-to-end | `backends/*`, `tools/_helpers.py`, +`test_backends.py` |
| `bb27995` | feat(transport): HTTP/SSE transport via `--transport` CLI flag | `__main__.py`, `README.md`, +`test_cli.py` |
| `204f373` | test(e2e): fake-claude shim + first CI-runnable subprocess tests | +`tests/fixtures/fake_claude.py`, +`test_e2e_fake_claude.py` |
| `7f67041` | feat(fan_out): optional `--synthesize` for unified summary | `tools/fan_out.py`, tests |
| (this commit) | ship: bump to v1.0.0a3 + retro | `__init__.py`, `README.md`, +retro doc |

**Diff vs v1.0.0a2**: 14 files changed, +1100 / −110 (estimated).

---

## Capabilities (this sprint)

### 1 · Backend Protocol tightening (review #4 from v1.0.0a1)

Public `Backend` Protocol is now two methods, both returning `BackendResult`:

```python
class Backend(Protocol):
    def ask_local(*, cwd, prompt, max_turns) -> BackendResult: ...
    def ask_remote(*, host, remote_cwd, prompt, max_turns,
                   connect_timeout, total_timeout) -> BackendResult: ...
```

`build_remote_command` and `parse_remote_stdout` are private to `ClaudeBackend`. SSH glue moved out of `tools/_helpers.run_backend` and into the backend itself, dropping `_helpers` by ~30 lines. Codex / Aider / Gemini drop-ins now ignore SSH entirely if they don't need it.

### 2 · HTTP/SSE transport

`harbormaster-mcp --transport sse|streamable-http --host 127.0.0.1 --port 7532`. `argparse`-based CLI with proper `--help`. Default still stdio (Claude Code / Desktop). Smoke-verified locally; uvicorn comes up clean.

### 3 · Fake-claude e2e infrastructure

`tests/fixtures/fake_claude.py` — Python script mimicking `claude -p` JSON contract. Failure modes via env var `HARBORMASTER_FAKE_CLAUDE_FAIL` (`timeout` / `exit2` / `garbage` / `empty`). 10 e2e tests in `tests/integration/test_e2e_fake_claude.py` exercise the **real** subprocess + JSON parse + `BackendResult` chain. CI-runnable on any machine with Python 3.11+, no Anthropic seat needed.

### 4 · `fan_out_ask --synthesize`

Optional second-pass: after collecting per-target answers, spawns one local `claude -p` that produces a unified summary at the top of the report. Off by default (cost). Skips gracefully when all targets errored.

### 5 · Single-source `__version__`

`pyproject.toml` now uses `dynamic = ["version"]` + `[tool.hatch.version] path = "src/harbormaster/__init__.py"`. `__init__.py` is the only literal — both build-time wheel metadata and runtime `importlib.metadata.version()` read from there. Drift risk gone.

---

## Real numbers

| Metric | v1.0.0a2 | v1.0.0a3 |
|--------|----------|----------|
| Source files | 16 | 16 (no new modules; existing files refactored) |
| Source LOC | ~1020 | ~1190 |
| Tests | 79 (78 + 1 skip) | 109 (108 + 1 skip) |
| MCP tools | 6 | 6 (`fan_out_ask` grew 2 params) |
| MCP transports | 1 (stdio) | 3 (stdio + sse + streamable-http) |
| Backend Protocol public methods | 3 | 2 |
| Test categories | unit + integration | unit + integration + e2e |
| `mypy --strict` | clean | clean |
| `ruff` | clean | clean |

---

## What worked

- **Sprint scope of 5 items, all shipped.** Tight focus, clean boundary on Live UI deferral. Each task = one commit. Diff is reviewable per-commit, not as a wall.
- **`fake_claude.py` shim** is the breakthrough this sprint enabled. Now every subsequent backend / tool change can be tested end-to-end without faking subprocess.run inline. The shim's failure-mode env var is a clean way to assert error handling without spawning real Claude.
- **Backend Protocol tightening** delivered the architectural wins the reviewer predicted: `_helpers.run_backend` is now obviously orchestration; SSH glue is encapsulated; future backends see a 2-method contract instead of a 3-method one with parsing concerns leaking out.
- **CLI argparse + `--help` discoverability**. Adding the `--transport` flag was small; reorganizing the entry point to surface every option in `--help` paid for itself the moment I had to document SSE in the README.
- **Single-source version with one re-sync to verify both paths**. Five-line build-system change, ten lines of confirmation. Highest reward-per-LOC of any task this sprint.

## What to change / next

- **`fan_out_ask` parameter list is approaching cluttered.** Seven keyword args. Next addition (auth headers? streaming output?) should pause and ask whether the tool wants a `FanOutOptions` dataclass instead of more positional/keyword args.
- **No live test of the SSE transport.** Smoke-verified by hand (uvicorn comes up + shuts down). Add a CI job that hits `/sse` over HTTP and asserts the lifecycle works end-to-end. Same shape as fake-claude — gated by environment.
- **`_get_backend` is private but imported across modules.** It's getting de-facto public via cross-module imports (fan_out reaches into _helpers). Promote to a public `get_backend` in `tools/__init__.py` next sprint to make the API contract explicit.
- **Synthesis in `Path.cwd()` is a slight cheat.** Works because synthesis doesn't need project context, but it means MCP server invocation from different cwds will resolve subprocess working directory differently. Consider a dedicated tmpdir or a top-level "harbormaster meta" notion later.

---

## Action items for the next sprint (v1.0.0a4 / week 4)

1. **Live UI scaffold** — FastAPI route + project grid + minimal SSE feed. The big remaining v1.0 deliverable. Architecture doc §7 already nailed the stack (HTMX + Alpine + Tailwind).
2. **FleetQ Bridge integration** — register harbormaster as a Bridge endpoint, heartbeat, deregister on shutdown. v1.1 phase from architecture doc kicks off here.
3. **Auth for HTTP/SSE transport** — bearer token from env var, 401 on missing/wrong. Required before the v1.0 GA tag can have `--host 0.0.0.0` examples in docs.
4. **CI live-SSE check** — gated job that starts the server with `--transport sse` and asserts the endpoint is reachable.
5. **`get_backend` public promotion** — clean up the de-facto-public private import.
6. **PyPI publish trigger** in CI on tag push, gated by GitHub environment / secret. Once v1.0.0a4 lands, flip the switch.

## Out-of-scope (still)

- Q&A history / federated KG / auto project graph — v1.2 roadmap.
- Backends other than Claude — wait for first user request.
- Plugin / extensions API — v2.

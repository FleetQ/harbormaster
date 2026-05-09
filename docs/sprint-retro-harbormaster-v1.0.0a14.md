# Sprint Retro — Harbormaster v1.0.0a14

**Date:** 2026-05-09
**Theme:** Streaming widening + refactor + cross-repo discipline.
The chunk-streaming path is now table-driven on `_STREAMING_TOOLS` so
adding new tools is one prompt builder away. `delegate_task` is the
first new arrival. On the FleetQ side, the popular-tool seeder PR
finally has its own pinning test, closing the testing-discipline gap
flagged in the previous retro.

## What landed

### `harbormaster` (this repo)

| SHA | Subject |
|-----|---------|
| `bdd7426` | feat(ui): widen chunk streaming to delegate_task + extract generic helpers (#8) |

### `agent-fleet` (community-edition base submodule)

| (squash) | test(seeders): pin Harbormaster popular-tool entry shape (#76) |

## Capabilities (this sprint)

### 1 · Refactor: dispatch is table-driven on `_STREAMING_TOOLS`

`make_ask_local_stream` / `make_ask_remote_stream` →
`make_local_backend_stream` / `make_remote_backend_stream`. Tool-
specific framing moved out (callers build the prompt). `name` →
`project_name` to disambiguate from MCP tool name. The SSE
dispatchers in `ui/routes.py` are now `_stream_local_tool` /
`_stream_remote_tool` parameterised on `(config, arguments,
prompt_builder, max_turns_default)`.

```python
_STREAMING_TOOLS: dict[str, PromptBuilder] = {
    "ask_project": _ask_project_prompt,
    "delegate_task": _delegate_task_prompt,
}
```

Adding chunk streaming for the next tool: write a prompt builder,
add it to `_STREAMING_TOOLS`. Done.

### 2 · `delegate_task` chunk streaming

`delegate_task` calls now stream the same way `ask_project` does:
one `chunk` SSE event per assistant text delta, then a final
`result` event with the assembled string.

`_delegate_task_prompt` injects the read-only framing:

```
Task: {task}

Deliverable: {deliverable}

Read-only mode. Do NOT edit files.
Report what you would do and which files you would touch.
Return markdown under 500 words.
```

Pre-flight argument validation:

| Bad arg | Result |
|---|---|
| missing/empty `task` | `event: error`, status 400 |
| missing/empty `deliverable` | `event: error`, status 400 |
| `allow_writes: true` | `event: error`, status 400 (v1 fail-closed; same as JSON path) |

The fail-closed semantics now happen **before** the subprocess
starts, instead of inside the tool body. Defense-in-depth — the
JSON path's check still runs too.

### 4 · `PopularToolsSeederTest` (cross-repo discipline)

PR #76 on `escapeboy/agent-fleet-o`: 4 PHPUnit cases pinning the
Harbormaster row in `PopularToolsSeeder`:

- Shape: slug, name, type=McpStdio, status=Disabled,
  risk_level=Read, transport command/args
- All 6 v1 tools advertised (canonical list)
- ask_project's input_schema fields (required + optional)
- Idempotent re-runs (`updateOrCreate(slug)` invariant)

First PHP test for any seeder in the agent-fleet repo. Pattern:
`RefreshDatabase` + `Team::factory()` in `setUp()`. Establishes
the precedent for future popular-tool entries.

## Real numbers

- 3/4 v1.0.0a13 retro action items shipped (items 2, 3 from a13
  retro; item 4 became this PR + PR #76; item 1 — A2A Agent Card —
  deferred to a15 since it's its own large deliverable)
- 2 PRs opened, both merged
  - 1 on FleetQ/harbormaster (#8)
  - 1 on escapeboy/agent-fleet-o (#76)
- 4 new tests on harbormaster + 4 new tests on agent-fleet
- Test suite delta: 238 → 242 passed on harbormaster; +4 on
  agent-fleet (first seeder test in the repo)
- Pint clean, ruff + mypy --strict clean across 26 source files
- 0 backward-incompatible changes (the rename was internal —
  routes.py was the only caller)

## What worked

- **Refactor + extension in the same PR.** Doing the
  `make_ask_*_stream` rename and adding `delegate_task` together
  forced the rename to actually justify itself. If the rename
  hadn't made the new tool trivial, we'd have noticed in the
  same diff. As it turned out, `delegate_task` was just a new
  prompt builder + an entry in `_STREAMING_TOOLS`.
- **Closing the testing discipline gap immediately.** PR #75
  shipped without a test in a13. PR #76 was a13's retro item #4.
  Doing it the *next* sprint instead of letting it linger
  preserves the credibility of the retro action items list.
- **Cross-repo retros in one document.** This retro lists both
  the harbormaster PR and the agent-fleet PR under "What landed."
  Reviewers don't need to dig through two retro files to see the
  full sprint surface.

## What to change / next

- **A2A Agent Card per project is the v1.1 elephant.** Listed in
  the a12 / a13 / a14 retros now. Larger than a typical sprint
  item — needs a `/agent-card/<project-name>` endpoint per
  project, an FleetQ-side consumer, and the A2A v0.3 schema. Worth
  blocking out a15 entirely for it instead of bundling.
- **`fan_out_ask` chunk streaming has no design doc yet.** The
  question for a15: do `chunk` events carry a `project` field
  (server-side multiplexing) or do callers maintain N parallel
  SSE streams? Both have tradeoffs. Worth a 1-page design before
  picking.
- **Cumulative session warning.** This is the **eighth** sprint
  shipped in one session (a8 → a14). The harbormaster repo has
  ~30 PRs merged in that span across the two repos. A future
  reader of the git log will see "every PR has tests, retro
  discipline, lint clean" but the velocity is unsustainable.
  Worth landing this retro and deferring v1.1 / v1.2 work to a
  fresh session for clearer thinking on the larger architectural
  decisions ahead.

## Action items for the next sprint (v1.0.0a15 / week 15)

1. **A2A Agent Card per project.** Each `~/htdocs/*` project
   exposes itself at `/agent-card/<project-name>` returning an
   A2A v0.3 agent card. From v1.1 §3.
2. **Design doc for `fan_out_ask` chunk streaming.** 1-pager
   in `docs/` exploring server-multiplexed chunks vs N-parallel
   streams.
3. **Production nginx config check.** Document
   `X-Accel-Buffering: no` requirement in
   `docs/architecture-harbormaster.md`. From the a11 retro,
   never shipped.
4. **Bump the Status section's roadmap table.** v1.0 phase is
   effectively done — local + SSH + Live UI + PyPI publish
   pipeline + streaming on both sides + v1.1 tooling foundation
   (Platform Tool seeder + test). The 6-week roadmap should
   re-baseline against current state.

## Out-of-scope (still)

- Q&A history / federated KG / auto project graph — v1.2 roadmap.
- Backends other than Claude — wait for first user request.
- Plugin / extensions API — v2.
- Tauri / Electron native UI wrapper — post-v1.2.
- Relay-binary path (Path B) — explicitly skipped in favour of Path C.
- Per-token streaming through the relay-mode bridge — relay
  frames are Redis chunks, not SSE.
- `fan_out_ask` chunk streaming — needs design doc (a15 #2 above).

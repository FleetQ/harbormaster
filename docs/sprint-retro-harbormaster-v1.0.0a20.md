# Sprint Retro — Harbormaster v1.0.0a20

**Date:** 2026-05-09
**Theme:** v1.2 phase 4 shipped — the **last lap before `v1.0.0` GA**.
The new `build_grounded_prompt` helper auto-prepends top-K recall
matches to `ask_project` / `delegate_task` prompts, so the subagent
sees prior answers without manual context loading. With this, the
v1.2 compounding phase is complete. Next sprint = drop the alpha
suffix and tag `v1.0.0`.

## What landed

### `harbormaster` (this repo)

| SHA | Subject |
|-----|---------|
| (squash) | feat(grounding): cross-session memory recall via auto-grounded prompts (v1.2 phase 4) (#14) |

## Capabilities (this sprint)

### 1 · `build_grounded_prompt` helper (v1.2 phase 4, item #1 from a19 retro)

`harbormaster.tools._grounding.build_grounded_prompt(question, project, host, config)`
prepends a "Prior context" section to the user's question with the
top-K matches from the per-host sqlite Q&A store. Three opt-in gates
(`[history] enabled` + `[history] auto_ground` + history package
importable) — all closed by default. When all three are open and
prior matches exist, the rendered output looks like:

```
<<<PRIOR CONTEXT (auto-loaded by harbormaster from past answers)>>>

### Past Q (project=alpha, tool=ask_project, score=0.91)
**Question:** How does authentication work?

**Answer:** JWT-based — see auth.md  …[truncated]

<<<END PRIOR CONTEXT>>>

Tell me about authentication
```

The subagent sees this as plain text inside its single-prompt
`claude -p` invocation. No new MCP tool, no new endpoint, no new wire
shape — pure prompt augmentation in `tools.ask` and `tools.delegate`
before `run_backend` is called.

### 2 · Char-capped context with score-ordered drop

`[history] auto_ground_max_chars` (default 8000 ≈ 2k tokens) bounds
the prepended context. Matches sort by score descending so when the
cap is hit, the lowest-score matches are dropped first — the strongest
ones always make it into the prompt. Individual answers > 1500 chars
are truncated mid-block to prevent a single huge answer from crowding
out smaller useful ones.

Edge case: if even the strongest single match exceeds the cap, the
helper falls back to passthrough rather than emit a misleading empty
context block.

### 3 · Silent failure semantics carry through

`build_grounded_prompt` follows the same fire-and-forget pattern as
a16's `_maybe_writeback_to_fleetq`: missing store, recall errors,
embedding failures, store-open exceptions — all log at WARNING and
return the original question unchanged. Better to ask without context
than to fail the whole tool call.

### 4 · `fan_out_ask` intentionally NOT auto-grounded

Multi-project parallel calls would multiply per-target recall
latency. Future: per-target grounding gated by an additional
`[history] auto_ground_fan_out` flag. Filed in §17.1 out-of-scope.

## Real numbers

- 1/4 v1.0.0a19 retro action items shipped (item #1 — phase 4)
- 1 PR opened, merged (#14) + 1 followup commit (operator-guide)
- 11 new tests (test_grounding) covering passthrough, top_k, project
  filter, char cap, individual-answer truncation, store-open and
  recall failure swallowing
- Test suite delta: 381 → 392 passed on harbormaster (1 skip)
- ruff clean, mypy --strict clean across 40 source files (was 39)
- 0 backward-incompatible changes

## What worked

- **Char cap with score-ordered drop instead of token cap.** Char
  count is cheap (`len(s)`) and 8000 chars ≈ 2k tokens is close
  enough for budget purposes without pulling in tiktoken or another
  tokeniser dep. When tokens become the actual cost, the cap can be
  swapped without changing the algorithm.
- **Same `_maybe_*` pattern as a16/a17/a19 hooks.** The grounding
  helper isn't named `_maybe_*` because it's not a side-effect hook
  — it computes a return value — but it shares the same gate-attempt-
  swallow-passthrough discipline. Once you've read one, you can
  predict how the next one behaves.
- **Subsection §17.1 instead of new §X.** Auto-grounding builds
  directly on the §17 Q&A history store; making it a subsection
  keeps the architecture doc's mental model coherent. Out-of-scope
  bullets that previously listed "auto-grounding" as a phase 4
  deferral now show it as DONE in the same section.

## What to change / next

- **`fan_out_ask` is the obvious next user request.** As soon as
  someone uses auto-grounding and notices their fan-out calls don't
  benefit, they'll ask. The implementation is straightforward: same
  helper, called per-target before each backend invocation. Filed for
  v2 because per-target latency cost needs real-world data first.
- **No grounding metric.** We don't track how often the prepended
  context actually changed the answer (would need to A/B per call).
  A future `harbormaster-mcp stats` subcommand could surface
  grounding hit rate alongside recall_count.
- **Streaming path doesn't auto-ground.** The `make_local_backend_stream`
  / `make_remote_backend_stream` paths bypass `tools.ask` and call the
  backend directly with a separately-built prompt in `ui/routes.py`.
  Auto-grounding only kicks in on the JSON path. Worth wiring once
  the streaming prompt builder lands in a more visible spot.
- **No grounding for KG triples yet.** The hook only consults the
  Q&A store; it doesn't pull triples from FleetQ even when both are
  enabled. Future combined grounding would need a FleetQ-side
  read-by-project endpoint that doesn't exist yet.

## Action items for the next sprint (v1.0.0 GA)

1. **Drop the alpha designation.** Bump `__version__` to `1.0.0`,
   tag `v1.0.0`, push tag → PyPI. No code change required; this is
   purely a version bump + retro.
2. **Write `docs/sprint-retro-harbormaster-v1.0.0.md`.** A summary
   retro spanning the full a1→GA arc. Lists all 20 alpha tags with
   one-line capabilities, total test growth, and what shipped vs.
   what was deferred.
3. **Update README status badge** from `alpha` → `stable`. Update
   the `## Status` section to reflect GA.
4. **Announce.** Optional: write a project-router-mcp v0.1 → GA
   release note for FleetQ Discord / GitHub releases page.

## Out-of-scope (still — for v2)

- Backends other than Claude.
- Plugin / extensions API.
- Tauri / Electron native UI wrapper.
- Relay-binary path (Path B).
- Per-token streaming through the relay-mode bridge.
- LLM-based triple extraction.
- Cross-host recall aggregation (depends on FleetQ-side aggregation).
- Embedding upgrade-in-place.
- Lockfile-driven version pinning.
- Transitive deps in graph.
- `auto_ground_fan_out` flag for fan_out_ask grounding.
- Grounding metric / hit-rate dashboard.
- Streaming-path auto-grounding.
- KG-triple-based grounding (combined with Q&A grounding).

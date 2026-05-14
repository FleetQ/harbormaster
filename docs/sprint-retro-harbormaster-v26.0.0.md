# Sprint Retro — harbormaster v26.0.0

**Date**: 2026-05-14
**Tag**: `v26.0.0`
**PR**: #29
**Commit**: `1692362`
**Wall-clock sprint duration**: ~3 hours (single conversational session)
**Phase**: Reflect (final phase of `/sprint-orchestrate full`)

## Goal

Side-step the Anthropic policy change effective 2026-06-15 — Agent SDK and `claude -p` programmatic usage moves to a separate $200/mo credit pool — by giving Harbormaster a new default execution mode where MCP tools return instruction packets to the calling interactive Claude TUI instead of spawning `claude -p` subprocesses themselves.

## Metrics

| Metric | Value |
|---|---|
| Files changed | 27 (14 modified, 13 new) |
| Lines added | 3,244 |
| Lines deleted | 50 |
| New MCP tools | 1 (`record_delegation_result`) |
| New config knobs | 2 (`execution_mode`, `awaiting_caller_timeout_seconds`) |
| Schema migrations | 3 idempotent columns (`execution_mode`, `tokens_used`, `rendered_prompt`) |
| New unit tests | 56 |
| Total unit tests passing | 1097 (1041 baseline + 56) |
| mypy --strict | clean (79 source files) |
| ruff | clean |
| Config-doc parity check | passes |
| Code-review HIGH findings | 3 (all resolved before commit) |
| Code-review MEDIUM findings | 4 (1 resolved, 3 deferred to v26.0.1) |

## Process — `/sprint-orchestrate full`

### What worked

1. **Forcing-questions framing in Think phase.** Writing `docs/design-v26-orchestrator-in-the-loop.md` with "who needs this, what's the narrowest version, what would make someone say 'whoa', how does this compound over time" produced a tight scope statement up front. The "no MVP — 100% working" directive from the operator was easy to align against, because the design doc made the full surface explicit.

2. **Plan-before-build discipline.** Writing `docs/architecture-v26-orchestrator-in-the-loop.md` and `docs/test-plan-v26-orchestrator-in-the-loop.md` before touching any code surfaced the SSH cross-host fallback rule and the orphan sweep TTL as policy questions to lock down — both ended up in the config schema rather than being hardcoded.

3. **Symbol-first exploration via Serena.** `find_symbol` / `get_symbols_overview` on every existing tool, backend, and job module before editing reduced the risk of breaking the Protocol-based dispatch chain. Total Serena memory + symbol calls < 20 — kept context usage low.

4. **Code review as a real gate.** The `ce-correctness-reviewer` agent surfaced three HIGH bugs that would have shipped:
   - Recovered packets dropping the role suffix (an `allow_writes=False` job's recovered Agent could have edited files — a real authorisation hole)
   - TOCTOU on `record_delegation_result` (concurrent retries double-firing subscribers)
   - Sweep race via separate UPDATE+SELECT
   All three were fixed in the same session before commit.

5. **Faithful test reporting.** Test counts (1041 → 1097), mypy / ruff status, and config-doc parity were captured verbatim in the commit message and PR body — operator can re-verify without trusting the assistant's narration.

### What didn't

1. **Test-fixture project setup.** Initial v26 tests failed because the fake `tmp_path / "fakeproj"` directories didn't have `.git` or `CLAUDE.md`, so `_is_project` rejected them. Caught quickly on the first pytest run, but should have been spotted at test-plan time. Pattern: every new test that calls `resolve_project` needs a marker file.

2. **Monkeypatching layer-mismatch.** When `delegate.py` switched from importing `run_backend` directly to `run_backend_or_instruction`, the existing six `monkeypatch.setattr(_delegate, "run_backend", ...)` calls in `test_tools.py` and `test_auto_commit.py` silently no-op'd. Caught on the first full-suite run. Pattern: when renaming a module-level binding consumed by tests, grep `monkeypatch.setattr.*<old_name>` and update those sites in the same commit.

3. **Fan-out instruction packet has known gaps.** The reviewer flagged that:
   - `batch_id` isn't persisted on the per-target rows (no correlation back to the fan-out invocation)
   - Partial-resolution failures (one target invalid) leave orphan `awaiting_caller` rows on the resolved siblings
   These are MEDIUM findings deferred to v26.0.1.

4. **No end-to-end test that the recovered packet actually preserves authorisation semantics in a running Agent.** Unit tests assert the marker is present in the recovered packet — but there's no integration test that an Agent invoked with the packet honours the suffix. Realistic limit for unit-test scope; would need a fake Anthropic backend or a Claude SDK harness.

## Learnings to capture in CLAUDE.md / memory

- **Decision provenance > raw config flag**: `execution_mode_for(config, host)` centralises the SSH-forces-subprocess rule. Going forward, every dispatch decision in Harbormaster should go through one such resolver, not direct `config.delegate.execution_mode` reads. Already applied retroactively to fan_out during the review fix.
- **Optimistic CAS belongs on every JobStore terminal-transition method**: `complete(expected_status=...)` and `fail(expected_status=...)` now exist; the JobWorker subprocess path still calls them without `expected_status` because it owns its row. Should consider adding the guard to the worker path too in v26.0.1 for symmetry.
- **`UPDATE ... RETURNING id` is the right idiom for sweep-and-notify patterns** in SQLite. Already used in `claim_next_queued`; now also in `sweep_stale_awaiting_caller`. The pattern of "UPDATE then SELECT by side-channel" is footgun-prone — always prefer RETURNING.
- **`rendered_prompt` column on JobStore** is the source of truth for instruction-mode packet recovery. Future schema evolution that affects what the Agent sees (e.g. CLAUDE.md auto-load contents) needs to keep this column stable.

## Followups (v26.0.x)

- [ ] Persist `batch_id` on fan-out per-target rows.
- [ ] Add JobWorker→`complete()` to use `expected_status=STATUS_RUNNING` for parity.
- [ ] UI: `/jobs` table — surface `execution_mode` column + `tokens_used` cost cell.
- [ ] Operator doc: walkthrough of the `claude setup-token` + `CLAUDE_CODE_OAUTH_TOKEN` flow for callers that want to verify they're routing through subscription pool. (Strictly belongs in operator-guide.md.)
- [ ] Track real-world cost-delta between v25 and v26 over the first 4 weeks of operation; revisit Approach 2/3 (worker daemon, smart proxy) only if data justifies them.

## Cost / risk reality check

Reviewer flagged the recovery-suffix and TOCTOU bugs as HIGH because both could have led to silent correctness violations:
- Suffix loss → an `allow_writes=False` recovered Agent could have edited files unauthorised.
- TOCTOU → concurrent record calls could have double-broadcast to FleetQ Bridge, polluting downstream agents' state.

Catching both pre-merge saved real damage. The pattern of `correctness reviewer → fix → re-test → ship` paid off well within the same session.

## Open question for the operator

The instruction packet uses a markdown rendering that depends on the calling assistant **recognising and acting on** the `HARBORMASTER_INSTRUCTION_V1` marker. The packet describes what to do in plain text — but there is no machine-enforced binding between "packet returned" and "Agent actually spawned with the right cwd / prompt / suffix." A misaligned calling assistant (e.g. a future MCP client without the packet-handling logic baked in) gets a markdown blob and silently does nothing useful. Mitigation today is the orphan sweep + the operator catching anomalies in `/jobs`. Worth tracking as a known limit.

# Design — v26.0.0 Orchestrator-in-the-loop Pivot

**Date**: 2026-05-14
**Phase**: Think
**Status**: Draft → Approved by operator (Nikola) on 2026-05-14
**Companion**: `architecture-v26-orchestrator-in-the-loop.md`, `test-plan-v26-orchestrator-in-the-loop.md`

## Problem Statement

Starting **June 15, 2026**, Anthropic decouples programmatic Claude usage (Agent SDK, `claude -p`, third-party apps authenticating via Agent SDK) from the Max plan's interactive usage pool. Programmatic calls now drain a separate **$200/mo monthly credit** (Max 20x), billed at full Claude API rates, non-rollover.

Harbormaster v25 ships an MCP server whose `delegate_task` / `ask_project` / `fan_out_ask` tools spawn `claude -p` subprocesses server-side — putting **every delegated task into the programmatic pool**. Log analysis (`claudedocs/research_anthropic_credit_policy_2026-05-14.md`) shows that:

- **97% of historical MCP calls happen in interactive hours** (08:00–23:59)
- **100% of delegate jobs were issued while the operator was in an interactive `claude` TUI session**
- Default Sonnet 4.6 burns $0.25–$0.47/call → naive workflow exhausts the $200 credit in **3–13 days**

The operator is already paying for an interactive Max 20x subscription. There is no reason to also burn the programmatic credit when the operator is sitting in front of a TUI that could spawn `Agent()` subagents for the same work — those subagents inherit the parent session's auth context and bill against the (much larger, interactive) subscription pool.

## Forcing Questions

### Who needs this? What are they doing today?

Single primary user: **Nikola Katsarov**, operating the FleetQ ecosystem from `~/htdocs/*` projects via interactive Claude Code TUI sessions. Today he calls `mcp__harbormaster__delegate_task(...)` from his TUI; Harbormaster shells out to `claude -p`; he waits for the result; iterates. Workflow distribution per 2-day measurement: **97% interactive, 92% allow_writes=True, median 50 turns, median 4 min wall time**.

Secondary user (later): FleetQ bridge tenants who consume Harbormaster as remote MCP. Out of scope for v26 — they will continue routing through `subprocess` execution mode and pay the programmatic credit cost.

### What's the narrowest version that ships value?

**Per operator directive**: no MVP. Full feature parity with v25's tool surface. `delegate_task`, `ask_project`, `fan_out_ask` all gain an `instruction` execution mode that returns an instruction packet for the calling assistant to execute via `Agent()`. Legacy `subprocess` mode preserved behind a config flag for SSH cross-host and unattended/cron scenarios.

### What would make someone say "whoa"?

The same Harbormaster MCP surface works without burning a cent of the $200 credit pool when the operator is interactive — and the operator doesn't need to change a single call site in their muscle memory. The only new tool is `record_delegation_result`, which the calling assistant transparently invokes after `Agent()` returns. End-to-end transparent cost shift from programmatic to interactive subscription pool.

### How does this compound over time?

1. **Cost-savings compound monthly**: every interactive delegate stays inside subscription pool; $200 programmatic credit reserved for true overnight/CI work.
2. **The instruction-mode contract becomes the foundation for future routing decisions**: same packet shape can route to local LLMs (cheap classification), Codex CLI (fallback), or stay in interactive Agent SDK pool. We're not building it today, but we're not blocking it either.
3. **JobStore becomes a pure orchestration journal**: as more execution modes accumulate, the JobStore tracks them without rewriting LLM-execution logic for each.
4. **Each task-result roundtrip captures real cost data** in the JobStore — building up the dataset we need to make future routing decisions empirically rather than by guess.

## Goals

1. Provide a config-driven `execution_mode` toggle: `"instruction"` (default, returns packet) | `"subprocess"` (legacy, preserves v25 behavior).
2. `delegate_task`, `ask_project`, `fan_out_ask` all support both modes with **identical caller-facing semantics** when caller honors the contract.
3. New MCP tool `record_delegation_result` for the caller to report execution outcomes back into the JobStore.
4. `await_delegated_task` / `await_inbox` / SSE `/jobs` page / completion publisher all continue to work — they fire when JobStore transitions to terminal status, regardless of which execution mode populated it.
5. Schema migration is idempotent and backward-compatible (existing rows do not need rewriting).
6. **Cross-host SSH hosts auto-fall-back to `subprocess`** for instruction mode (because the calling assistant has no PTY to that host). v26 does not solve SSH-via-instruction; we explicitly keep subprocess for that case.
7. **Zero regressions** on the existing 1041 unit tests.
8. Comprehensive new test coverage for v26 paths (≥30 new tests).
9. Operator-facing docs (`operator-config-reference.md`, dashboard hint copy) updated.

## Non-Goals

1. Local LLM backend / smart proxy (Approaches 2 & 3 from the research report) — deferred.
2. Codex fallback wiring — deferred to v26.1.
3. Worker daemon pattern — deferred; user is bullish but data shows it's not needed yet.
4. UI redesign — minimal additions to `/jobs` page only.
5. Migration of historical FleetQ Bridge endpoint to instruction mode — bridge continues to consume completion events as before.
6. Token/cost attribution in JobStore — design hook present (caller can pass `tokens_used` to `record_delegation_result`), but no UI rendering of cost data in v26. Foundation for v26.1.

## Approach Summary

1. New backend type `InstructionBackend(Backend)` implements the same Protocol as `ClaudeBackend` / `CodexBackend` but instead of invoking an LLM, **packages a structured "instruction packet"** into the `BackendResult.text` field with a marker (`HARBORMASTER_INSTRUCTION_V1`).
2. The job is persisted in `JobStore` with new status `awaiting_caller` (added to `VALID_STATUSES`). `started_at` is left null until the caller acknowledges with `record_delegation_result`.
3. New MCP tool `record_delegation_result(job_id, status, output, error?, duration_ms?, tokens_used?)` validates the job is in `awaiting_caller`, transitions through `running` → `completed`/`failed`, fires the existing completion fan-out (Event/Condition/subscribers/SSE/publisher).
4. `delegate_task` tool: if cfg execution_mode = `"instruction"` AND host is local AND backend is `claude`, route through `InstructionBackend`; else route through legacy `ClaudeBackend.ask_local` or `.ask_remote`.
5. `ask_project` tool: same dispatch logic; sync caller pattern is "caller-executes-then-records".
6. `fan_out_ask` tool: in instruction mode returns N instruction packets in a batch envelope.
7. UI: `/jobs` table grows two columns — `execution_mode` (instruction/subprocess) and a `tokens_used` hint where present.
8. Operator config: new `[delegate]` block `execution_mode = "instruction" | "subprocess"`, default `"instruction"`. Documented in `operator-config-reference.md`.
9. Comprehensive unit tests in `tests/unit/test_v26_*.py` (new files) plus regression tests on every existing test that touches `delegate_task` / `ask_project` / `fan_out_ask` / JobStore status transitions.

## Resolved Design Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Default execution mode | `instruction` | Aligned with operator workflow data (97% interactive) |
| Legacy `subprocess` mode | Retained as opt-in via config | Preserves SSH, async/cron, bridge use cases |
| SSH cross-host handling | Auto-fallback to subprocess | Calling assistant has no remote PTY |
| `model` field semantics | Caller-controlled in subprocess; hint-only in instruction mode | Caller's Agent() controls actual model dispatch |
| Async API surface | Preserved verbatim | Async + instruction = "pending packet that caller fetches later" |
| `record_delegation_result` permissions | Anyone with MCP write access; idempotent on terminal state | Simple contract, matches existing tools |
| Instruction packet format | Versioned JSON (`HARBORMASTER_INSTRUCTION_V1`) | Forward-compat with future routing layers |

## Operator-Facing Changes

1. `~/.harbormaster/config.toml` may add `[delegate] execution_mode = "instruction"` (or `"subprocess"` to opt back into v25 behavior). Default is `instruction` if absent.
2. Behavior shift: when the operator's interactive Claude assistant calls `delegate_task`, it receives an instruction packet instead of a finished result. The assistant is expected to **execute the packet via its `Agent()` tool** and then call `record_delegation_result`. This is documented as the standard pattern.
3. If a v25 caller (no `record_delegation_result` knowledge) hits instruction mode, it gets the packet as a markdown block — the call still "succeeds" but the JobStore stays in `awaiting_caller` forever. We add a sweep job that times out `awaiting_caller` rows older than 1 hour to `failed` with error "caller never recorded result".

## Success Criteria

- [ ] Operator runs `harbormaster-mcp` from main project dir; `delegate_task` returns instruction packet without spawning any subprocess. Validated by `lsof` showing no `claude` child of harbormaster-mcp.
- [ ] Calling assistant executes packet via `Agent()` → `Agent()` runs in the same parent TUI process → API call hits subscription pool, **not** programmatic credit (verifiable via `~/.claude/usage` if Anthropic exposes split metric, or via comparing the operator's $200 credit consumption rate before/after the change).
- [ ] `record_delegation_result` transitions job to terminal status, fires SSE event, posts to FleetQ bridge if armed.
- [ ] Setting `execution_mode = "subprocess"` reverts behavior to v25 byte-for-byte.
- [ ] 100% pass on 1041+ existing tests + 30+ new tests.
- [ ] Documentation parity (`scripts/check_config_doc_parity.py` passes).
- [ ] `mypy --strict` clean, `ruff` clean.

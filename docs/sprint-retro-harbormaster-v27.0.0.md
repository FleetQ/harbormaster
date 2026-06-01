# Sprint Retro — harbormaster v27.0.0

**Theme**: Provider-agnostic orchestrator — instruction-mode packets for non-Claude
MCP clients (Codex CLI, Gemini CLI, generic agentic clients).

**Date**: 2026-06-01
**Branch**: `feat/provider-agnostic-orchestrator`

## What shipped

v26 made instruction mode the default but the packet was hard-coupled to Claude
Code (`Agent`/`Task`, `subagent_type`). v27 adds an **orchestrator adapter** layer
so a non-Claude calling client receives a packet in its own sub-agent idiom and can
auto-execute it — broadening MCP-client compatibility without touching the
already-provider-agnostic executing/`Backend` side.

1. **New module `src/harbormaster/orchestrators.py`** — `OrchestratorAdapter`
   Protocol + `ClaudeAdapter` (delegates to the v26 renderer, byte-for-byte),
   `CodexAdapter`, `GeminiAdapter`, `NeutralAdapter`; registry + `get_adapter` +
   `register_adapter` (plugin seam); `resolve_orchestrator` (single source of
   truth) and best-effort `detect_client_orchestrator` (reads the MCP `request_ctx`
   contextvar → `clientInfo.name`).
2. **Config** — `[delegate] orchestrator = "auto"` (auto-detect → `claude`
   fallback; or pin `claude`/`codex`/`gemini`/`neutral`).
3. **Schema/store** — nullable `orchestrator` column + idempotent migration; `Job`
   field + `as_dict` + `enqueue` param.
4. **Tools** — `ask_project` / `delegate_task` / `fan_out_ask` gain an
   `orchestrator` param. Resolution precedence: explicit param > config (≠ `auto`) >
   clientInfo auto-detect > `claude`. Unknown orchestrator → transparent subprocess
   fallback across all three tool paths (sync, delegate-async, fan-out).
5. **Recovery** — `get_delegated_task` rebuilds the packet via the row's adapter
   (NULL → claude).
6. **UI** — `orchestrator` surfaced in the `/jobs` expanded detail panel.

## Pre-work (Think + validation)

- Brainstorm → `docs/requirements-provider-agnostic-orchestrator.md`.
- **OQ-1 validated** (web research): Codex CLI + Gemini CLI both ship subagent
  delegation with arbitrary task prompts; delegation is LLM-mediated so the
  markdown-packet contract generalises. Constraint surfaced: neither has a
  per-delegation `cwd` arg → non-Claude packets embed the path in the prompt body.
- **OQ-2 validated** (SDK probe): `mcp==1.27.0` exposes the `request_ctx` contextvar
  → `clientInfo.name`, so auto-detect needs no tool-signature change.

## Backward-compat invariants (held; adversarially reviewed)

- Default `auto` + Claude/undetected caller → v26 packet byte-for-byte, row
  `orchestrator="claude"`.
- Unknown orchestrator never yields a broken packet or an orphan `awaiting_caller`
  row — subprocess fallback is gated before any enqueue in all three paths.
- SSH/remote still forced to subprocess via `execution_mode_for` (unchanged).
- `detect_client_orchestrator` never raises into a tool call.

## Tests

- 53 new v27 unit tests (`tests/unit/test_v27_orchestrator_*.py`): resolver,
  adapters, detection, schema/store, tool wiring + fallback, recovery.
- **2181 passed, 1 skip** total; `mypy --strict` + `ruff` clean.

## Review findings (adversarial) — dispositions

- *Auto-detect substring false-positive* (low): in-spec, documented as best-effort
  (OQ-6). No change.
- *Fan-out error/null target in packet* (low, near-dead path): added explicit
  "skip targets with an `error`/null `job_id`" clause to the generic fan-out packet.
- *`job_id` repr-quoting in report-back table* (low): render plain `job_id` in the
  non-Claude packet to avoid quote-wrapped copy-paste orphaning the row.

## Key learnings

- The v26 markdown-packet design generalised cleanly: per-orchestrator adapters are
  ~wording, not a new transport — because every target CLI's delegation is
  LLM-mediated, just like the original Claude packet.
- `request_ctx` (lowlevel) — not `FastMCP.get_context()` (an instance method) — is
  the right entry point for client identity from a stateless helper.
- The cwd-in-prompt constraint is convention-only (no code enforcement) for ALL
  adapters including Claude — the highest-consequence assumption; guarded by a test
  asserting the path is present in write-enabled non-Claude packets.

## Deferred / future

- Plugin-registered third-party adapters (seam present, not shipped).
- Antigravity CLI (Gemini CLI successor, 2026-06-18) — currently mapped to the
  `gemini` adapter via substring; verify the subagent contract carries over (OQ-7).
- Empirical `clientInfo.name` mapping table per CLI (OQ-6).

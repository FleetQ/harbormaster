# Test Plan — Provider-Agnostic Orchestrator

Derives from the architecture doc. New tests live in
`tests/unit/test_v27_orchestrator_*.py` (mirrors source). All existing v26 tests
MUST pass unmodified.

## Unit — resolver (`test_v27_orchestrator_resolver.py`)

- `explicit` param wins over config and client_name.
- config (non-`auto`) wins over client_name; ignored when `explicit` set.
- `auto` config + recognised client_name → mapped adapter.
- `auto` config + unrecognised client_name → `claude` default.
- `auto` config + None client_name → `claude` default.
- case-insensitivity / whitespace trim on explicit + config.
- `_map_client_name`: `claude-code`→claude, `codex`→codex, `gemini-cli`→gemini,
  `antigravity`→gemini, `cursor`→None (unmapped).

## Unit — adapters (`test_v27_orchestrator_adapters.py`)

- `ClaudeAdapter.render_packet` == `InstructionPacket.to_markdown()` byte-for-byte
  (FR-7 guard).
- `ClaudeAdapter.render_fan_out` == `instruction.build_fan_out_packet(...)`.
- Codex/Gemini/Neutral packets all contain: `INSTRUCTION_MARKER`, the job_id, the
  project path (cwd embedded in body, per OQ-1 constraint), and an instruction to
  call `record_delegation_result`.
- Codex/Gemini/Neutral packets do NOT contain Claude-isms
  (`subagent_type`, "Task tool").
- `get_adapter` returns the right instance for each name; `None` for unknown.
- `register_adapter` adds a new adapter retrievable via `get_adapter` (plugin seam).

## Unit — detection (`test_v27_orchestrator_detect.py`)

- `detect_client_orchestrator()` returns None when no request context (raises
  swallowed).
- with a fake context whose `client_params.clientInfo.name = "codex"` → "codex".
- malformed/None client_params → None (no raise).

## Unit — schema/store (`test_v27_orchestrator_store.py`)

- pre-v27 DB (no `orchestrator` column) migrates to add it; existing rows read back
  with `orchestrator=None`.
- `enqueue(orchestrator="codex")` persists; `get` round-trips it; `as_dict`
  includes `orchestrator`.
- `enqueue()` default → `orchestrator=None`.

## Unit — dispatch wiring (`test_v27_orchestrator_dispatch.py`)

- `run_backend_or_instruction` instruction mode + `orchestrator="gemini"` → returns
  a Gemini packet; row persisted with `orchestrator="gemini"`.
- instruction mode + unknown orchestrator (`"bogus"`) → subprocess fallback
  (`run_backend` invoked; no `awaiting_caller` row). Assert via monkeypatched
  backend + log/warning.
- instruction mode + default (auto, no client) → claude packet (FR-7) + row
  `orchestrator="claude"`.
- SSH host → subprocess regardless of orchestrator param (existing rule).

## Unit — tool params (`test_v27_orchestrator_tools.py`)

- `ask_project(orchestrator="codex")` → codex packet.
- `delegate_task(orchestrator="gemini")` sync → gemini packet; row persisted.
- `delegate_task(orchestrator="gemini", mode="async")` → `awaiting_caller` row with
  `orchestrator="gemini"`; handle string returned.
- `delegate_task(orchestrator="bogus", mode="async")` → subprocess-async (`queued`
  row, no orchestrator).
- `fan_out_ask(orchestrator="codex")` all-local → codex fan-out packet; every row
  shares batch_id AND `orchestrator="codex"`.
- `fan_out_ask(orchestrator="bogus")` → subprocess ThreadPool path (no
  awaiting_caller rows).

## Unit — recovery (`test_v27_orchestrator_recovery.py`)

- `get_delegated_task` on an `awaiting_caller` row enqueued with
  `orchestrator="codex"` → `instruction_packet` rendered by the Codex adapter.
- row with `orchestrator=None` (legacy) → claude adapter (default).

## Regression

- Full `tests/unit` + `tests/integration` + UI suites green (2128 baseline).
- `mypy --strict src/harbormaster/` clean.
- `ruff check src/ tests/` clean.

## Acceptance mapping

| Requirement | Test(s) |
|---|---|
| FR-1 resolver chain | resolver |
| FR-2 per-orchestrator rendering + cwd-in-prompt | adapters |
| FR-3 unknown → subprocess fallback | dispatch, tools |
| FR-4 universal report-back | (unchanged — covered by v26 record_result tests) |
| FR-5 fan-out adapter aware + batch_id | tools |
| FR-6 recovery fidelity | recovery |
| FR-7 Claude byte-for-byte | adapters, dispatch |
| FR-8 observability | (UI — manual smoke; field in as_dict covered by store) |

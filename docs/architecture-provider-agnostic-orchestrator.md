# Architecture — Provider-Agnostic Orchestrator (instruction mode)

**Status**: Plan (sprint phase 2). Derives from
`docs/requirements-provider-agnostic-orchestrator.md`. OQ-1 + OQ-2 validated
positive (2026-06-01).

## Validated facts driving the design

- **OQ-1**: Codex CLI and Gemini CLI both ship subagent delegation where the
  orchestrator LLM spawns a sub-agent with an arbitrary prompt; sub-agents have
  MCP/tool access and return a result. Delegation is LLM-mediated (the orchestrator
  reads instructions and decides), so the markdown-packet approach generalises — a
  per-orchestrator adapter is mostly **idiom/wording**, not a different transport.
- **OQ-1 constraint**: neither Codex nor Gemini has a per-delegation `cwd`
  argument. Non-Claude packets must embed the project path **in the prompt body**.
- **OQ-2**: `mcp==1.27.0` exposes `FastMCP.get_context()` →
  `Context.session.client_params.clientInfo.name`. Best-effort client auto-detect
  is implementable **without changing tool signatures** (read via contextvar).

## Components

### 1. New module `src/harbormaster/orchestrators.py`

The adapter layer + resolver. Imports only `instruction` + `config` (no cycle).

- `OrchestratorAdapter` (Protocol): `name: str`,
  `render_packet(packet: InstructionPacket) -> str`,
  `render_fan_out(*, batch_id, targets, synthesize, synthesis_max_turns, model_hint) -> str`.
- Concrete adapters:
  - `ClaudeAdapter` — delegates to the **existing** `InstructionPacket.to_markdown()`
    and `instruction.build_fan_out_packet(...)`. Guarantees v26.0.1 byte-for-byte
    output (FR-7).
  - `CodexAdapter` — Codex idiom ("Spawn an agent…", project path in prompt body,
    report via harbormaster's `record_delegation_result`, note Codex's own
    `report_agent_job_result` is NOT the callback).
  - `GeminiAdapter` — Gemini idiom (`@generalist` delegation, project path in prompt
    body). Covers Gemini CLI + Antigravity-family.
  - `NeutralAdapter` — provider-neutral wording + machine-readable JSON descriptor,
    no vendor tool names. Explicit opt-in only.
- Registry `_ORCHESTRATOR_ADAPTERS: dict[str, OrchestratorAdapter]` +
  `get_adapter(name) -> OrchestratorAdapter | None` + `register_adapter(adapter)`
  seam (NFR-6: plugin path later, no refactor).
- `DEFAULT_ORCHESTRATOR = "claude"` — preserves v26 default behaviour.
- `_CLIENT_NAME_PATTERNS` — substring → adapter map for clientInfo auto-detect
  (`claude`→claude, `codex`→codex, `gemini`/`antigravity`→gemini). Best-effort
  (OQ-6: empirical strings unconfirmed).
- `detect_client_orchestrator() -> str | None` — best-effort read of
  `FastMCP.get_context().session.client_params.clientInfo.name`, fully wrapped in
  try/except (returns None outside a request context / pre-init / SDK drift).
- `resolve_orchestrator(*, explicit, config, client_name) -> str` — the single
  source of truth (NFR-5), precedence chain:
  1. `explicit` tool param (lowercased)
  2. `config.delegate.orchestrator` when != `"auto"`
  3. `client_name` mapped to a known adapter (auto-detect)
  4. `DEFAULT_ORCHESTRATOR` (`"claude"`)

### 2. `config.py` — `DelegateConfig.orchestrator: str = "auto"`

`"auto"` = use clientInfo detection, fall back to `claude`. Any explicit value
(`claude`/`codex`/`gemini`/`neutral`/unknown) pins the deployment.

### 3. `jobs/schema.py` + `jobs/store.py` — persist the resolved orchestrator

- New migration `("orchestrator", "orchestrator TEXT")` (nullable; NULL for
  subprocess rows). Mirrors the v26 migration pattern.
- `Job` dataclass gains `orchestrator: str | None = None`; `as_dict()` exposes it;
  `_row_to_job` reads it with the `"col" in row_keys` guard.
- `enqueue(..., orchestrator: str | None = None)` writes the column.

### 4. `tools/_helpers.py` — dispatch + FR-3 fallback

- `run_instruction(..., orchestrator: str)` renders via
  `get_adapter(orchestrator).render_packet(...)` and persists `orchestrator` on the
  row.
- `run_backend_or_instruction(..., orchestrator: str | None)`:
  ```
  mode = execution_mode_for(config, host)        # SSH/subprocess unchanged
  if mode == "instruction":
      orch = resolve_orchestrator(explicit=orchestrator, config=config,
                                  client_name=detect_client_orchestrator())
      if get_adapter(orch) is not None:
          return run_instruction(..., orchestrator=orch)
      logger.warning("unknown orchestrator %r → subprocess fallback", orch)  # FR-3
  return run_backend(...)
  ```
  Because the resolver defaults to `claude` (a known adapter), the subprocess
  fallback only fires when an explicit param / config names an **unknown**
  orchestrator — exactly FR-3.

### 5. `tools/ask.py`, `delegate.py`, `fan_out.py` — new `orchestrator` param

- `ask_project` / `delegate_task` / `fan_out_ask` gain
  `orchestrator: str | None = None`, threaded to the helpers.
- `delegate_task` async-instruction branch: resolve; if known adapter → enqueue
  `awaiting_caller` with `orchestrator` persisted; else enqueue subprocess-async
  (`queued`) so a JobWorker runs it (FR-3 for the async path).
- `fan_out_ask` `all_instruction` gate additionally requires the resolved
  orchestrator to be a known adapter; otherwise fall through to the existing
  subprocess ThreadPool path. `_instruction_fan_out` renders via
  `adapter.render_fan_out(...)` and persists `orchestrator` on every row.

### 6. `tools/job_status.py` — adapter-aware recovery (FR-6)

`get_delegated_task` rebuilds the `awaiting_caller` packet via
`get_adapter(job.orchestrator or "claude").render_packet(...)`, so a recovered
packet matches the adapter that produced it.

### 7. `ui/templates/jobs.html` — observability (FR-8)

Add `orchestrator` to the expanded per-row detail panel (alongside
`execution_mode` / `tokens_used` / `batch_id`). No new grid column — keeps the grid
stable; detail panel is the established place for provenance fields.

## Data flow (instruction mode, non-Claude orchestrator)

```
caller (Codex CLI) → ask_project(orchestrator="codex" | auto-detect)
  → run_backend_or_instruction
    → resolve_orchestrator → "codex"
    → get_adapter("codex") ✓
    → run_instruction(orchestrator="codex")
        → store.enqueue(execution_mode="instruction",
                        initial_status="awaiting_caller",
                        orchestrator="codex", rendered_prompt=...)
        → CodexAdapter.render_packet(packet)   # codex idiom, cwd in prompt
  → returns codex-flavoured packet
caller spawns Codex sub-agent → calls record_delegation_result(job_id, ...)
  → JobStore.complete(expected_status="awaiting_caller")  # unchanged CAS
  → _fire_completion fan-out (SSE / Bridge / waiters)     # unchanged
```

## Backward-compat invariants

- Default config (`orchestrator="auto"`) + Claude caller (clientInfo `claude*` or
  undetected) → `claude` adapter → v26.0.1 packet byte-for-byte (FR-7).
- All existing v26 tests pass unmodified (the claude path is untouched; new params
  default to `None`/`"auto"`).
- SSH still forced to subprocess via `execution_mode_for` (unchanged).

## Out of scope (this sprint)

Plugin-registered third-party adapters (seam present, not shipped); billing parity
for non-Claude; non-MCP report-back transport.

# Architecture — v26.0.0 Orchestrator-in-the-loop Pivot

**Date**: 2026-05-14
**Phase**: Plan
**Status**: Approved
**Companion**: `design-v26-orchestrator-in-the-loop.md`, `test-plan-v26-orchestrator-in-the-loop.md`

## Component Diagram (delta vs v25)

```
                ┌──────────────────────────────────────────┐
                │  MCP CLIENT (interactive `claude` TUI)   │
                │                                          │
                │   parent ╔═════════════════════╗         │
                │   auth ▶ ║ subscription pool   ║         │
                │          ╚═════════════════════╝         │
                └──────────────┬───────────────────────────┘
                               │ MCP
                               ▼
            ┌──────────────────────────────────────────┐
            │  harbormaster-mcp (this repo)            │
            │                                          │
            │  delegate_task ──► InstructionBackend ──►│  packet to caller
            │  ask_project   ──► InstructionBackend ──►│  packet to caller
            │  fan_out_ask   ──► InstructionBackend ──►│  N packets to caller
            │                                          │
            │  ── execution_mode == "instruction" ─────│
            │      packet contains: project_path,      │
            │      cwd, prompt, agent_options,         │
            │      callback_tool, job_id               │
            │                                          │
            │  JobStore (added status: awaiting_caller)│
            │                                          │
            │  record_delegation_result  ◄─────────────│  caller reports back
            │      → JobStore.complete/fail            │
            │      → _fire_completion (existing fan-out│
            │        SSE / publisher / Event / Cond)   │
            │                                          │
            │  ── execution_mode == "subprocess" ──────│
            │      legacy path: ClaudeBackend.ask_*    │
            │      (spawns `claude -p`, returns text)  │
            └──────────────────────────────────────────┘

           Caller workflow (instruction mode):
           1. Calls mcp__harbormaster__delegate_task(...)
           2. Receives instruction packet
           3. Caller spawns Agent(prompt=..., cwd=...) — runs in caller's
              process auth context → subscription pool
           4. Caller calls mcp__harbormaster__record_delegation_result(
                  job_id, status, output, ...)
           5. Subscribers (SSE, FleetQ Bridge publisher) fire identically
              to v25 subprocess completion.
```

## Files Touched

### New files

```
src/harbormaster/backends/instruction.py     # InstructionBackend(Backend)
src/harbormaster/tools/record_result.py      # MCP tool record_delegation_result
src/harbormaster/tools/_instruction_packet.py # shared packet formatter
tests/unit/test_v26_instruction_backend.py   # ~10 tests
tests/unit/test_v26_record_result.py         # ~10 tests
tests/unit/test_v26_delegate_instruction.py  # ~7 tests
tests/unit/test_v26_ask_instruction.py       # ~5 tests
tests/unit/test_v26_fan_out_instruction.py   # ~5 tests
tests/unit/test_v26_schema_migration.py      # ~3 tests
```

### Modified files

```
src/harbormaster/__init__.py                 # version 25.0.0 → 26.0.0
src/harbormaster/config.py                   # DelegateConfig.execution_mode + new fields
src/harbormaster/backends/__init__.py        # export InstructionBackend, registration
src/harbormaster/jobs/schema.py              # STATUS_AWAITING_CALLER + migration tuple
src/harbormaster/jobs/store.py               # enqueue_instruction, awaiting_caller in recover_orphaned
src/harbormaster/tools/__init__.py           # register record_result
src/harbormaster/tools/_helpers.py           # run_backend_or_instruction wrapper
src/harbormaster/tools/delegate.py           # branch on execution_mode
src/harbormaster/tools/ask.py                # branch on execution_mode
src/harbormaster/tools/fan_out.py            # branch on execution_mode (per-target)
src/harbormaster/tools/job_status.py         # surface awaiting_caller in get_delegated_task
src/harbormaster/ui/templates/jobs.html      # show execution_mode + tokens columns
docs/operator-config-reference.md            # document new [delegate] knobs
docs/architecture-harbormaster.md            # delta note
```

### Tests touched (regression coverage)

```
tests/unit/test_delegate.py                  # add execution_mode='subprocess' fixture
tests/unit/test_ask.py                       # same
tests/unit/test_fan_out.py                   # same
tests/unit/test_jobs_store.py                # awaiting_caller transitions
tests/unit/test_jobs_wait.py                 # awaiting_caller transitions
tests/unit/test_v15_precommit_integration.py # config doc parity
```

## Configuration Schema Additions

```python
class DelegateConfig(BaseModel):
    model_config = _FORBID_EXTRA

    retain_recent_k: int = Field(default=1000, gt=0)
    worker_count: int = Field(default=1, gt=0, le=16)

    # v26.0.0 — orchestrator-in-the-loop.
    # "instruction" (default): delegate_task/ask_project/fan_out_ask return
    #   an instruction packet for the calling assistant to execute via its
    #   own Agent() / Task tool. Job is persisted as `awaiting_caller`;
    #   caller MUST report via record_delegation_result.
    # "subprocess" (legacy v25): tool spawns `claude -p` server-side and
    #   blocks until completion. Required for SSH cross-host, cron, and
    #   any unattended scenario.
    execution_mode: Literal["instruction", "subprocess"] = "instruction"

    # v26.0.0 — orphan sweep for awaiting_caller jobs the caller never
    # records. Set to 0 to disable; otherwise jobs older than this many
    # seconds get swept to failed with error "caller never recorded result".
    awaiting_caller_timeout_seconds: int = Field(default=3600, ge=0)
```

## JobStore Schema Migration

```python
# In src/harbormaster/jobs/schema.py:
STATUS_AWAITING_CALLER = "awaiting_caller"   # NEW
VALID_STATUSES = frozenset({
    STATUS_QUEUED, STATUS_RUNNING, STATUS_COMPLETED, STATUS_FAILED,
    STATUS_AWAITING_CALLER,   # NEW
})

# New idempotent migration entry:
MIGRATIONS.append(
    ("execution_mode", "execution_mode TEXT NOT NULL DEFAULT 'subprocess'"),
)
MIGRATIONS.append(
    ("tokens_used", "tokens_used INTEGER"),
)
```

Schema is forward+backward compatible:
- Pre-v26 rows get `execution_mode = 'subprocess'` (matches their actual provenance).
- New rows record their actual provenance.
- `tokens_used` is nullable, defaults NULL — only populated when caller passes it via `record_delegation_result`.

## Instruction Packet — Wire Format

`HARBORMASTER_INSTRUCTION_V1` is the discriminator. The packet is returned as **markdown with an embedded JSON code block**, so the assistant reads it like any other tool response, recognizes the marker, and acts accordingly.

```markdown
# Harbormaster instruction packet — execute and report back

**Marker**: HARBORMASTER_INSTRUCTION_V1
**Job ID**: `01HZ...`
**Project**: `agent-fleet`
**Working dir**: `/Users/katsarov/htdocs/agent-fleet`
**Mode**: delegate-writes-allowed (or `ask`, `delegate-readonly`, `fan-out`)
**Max turns hint**: 50

## Spawn Agent

Call `Agent` with:

```json
{
  "description": "Delegate to agent-fleet",
  "subagent_type": "general-purpose",
  "prompt": "<full prompt — grounding + task + deliverable + suffix>",
  "isolation": null
}
```

## When the Agent returns, call

```
mcp__harbormaster__record_delegation_result(
    job_id="01HZ...",
    status="completed",      # or "failed"
    output="<Agent return text>",
    error=null,              # if failed, error reason here
    duration_ms=<ms>,
    tokens_used=<n>          # optional, cumulative
)
```

If Agent raises or exits non-zero: pass `status="failed"` and `error=<reason>`.
```

The marker is the contract. Callers that recognize it execute the Agent.
Callers that don't recognize it see a human-readable instruction and can either follow it or ignore it (with the orphan-sweep cleaning up later).

## Backend Protocol Extension

`InstructionBackend` implements the existing `Backend` Protocol:

```python
class InstructionBackend:
    name: str = "instruction"
    cfg: BackendConfig

    def __init__(self, cfg: BackendConfig, store: JobStore, packet_factory):
        self.cfg = cfg
        self._store = store
        self._packet_factory = packet_factory  # callable(job_id, ...) -> str

    def ask_local(self, *, cwd, prompt, max_turns, model=None) -> BackendResult:
        # NOTE: ask_local for instruction mode creates the JobStore row
        # with status=awaiting_caller and returns the packet as its output.
        # This intentionally returns immediately (no wait, no LLM call).
        ...

    def ask_remote(...) -> BackendResult:
        # NOT SUPPORTED — raises BackendError(code="instruction_no_remote").
        # SSH cross-host always falls back to subprocess at the tool layer.
        raise BackendError(
            code="instruction_no_remote",
            message="InstructionBackend does not support remote SSH "
                    "execution; use execution_mode='subprocess' for SSH hosts.",
        )
```

Tool layer (`_helpers.run_backend_or_instruction`) dispatches:

```python
def run_backend_or_instruction(
    *,
    name, prompt, max_turns, host, config, label_prefix,
    model=None,
    job_metadata: JobMetadata,  # carries the inputs needed to enqueue + packet
) -> str:
    if config.delegate.execution_mode == "subprocess" or is_remote(host):
        return run_backend(...)  # existing v25 path

    # instruction mode, local only
    return _build_instruction_packet(
        config=config,
        name=name,
        host=host,
        prompt=prompt,
        max_turns=max_turns,
        model=model,
        label_prefix=label_prefix,
        job_metadata=job_metadata,
    )
```

## Tool Surface Changes

### `delegate_task` (modified)

Signature unchanged. Behavior:
- `mode='sync'` + `execution_mode='instruction'` → enqueues `awaiting_caller`, returns packet.
- `mode='sync'` + `execution_mode='subprocess'` → existing v25 behavior.
- `mode='async'` + `execution_mode='instruction'` → enqueues `awaiting_caller`, returns short handle. Caller polls via `get_delegated_task(job_id)` which returns the packet.
- `mode='async'` + `execution_mode='subprocess'` → existing v25 behavior.

### `ask_project` (modified)

Signature unchanged. Behavior:
- `execution_mode='instruction'` → enqueues `awaiting_caller`, returns packet.
- `execution_mode='subprocess'` → existing v25 behavior.
- SSH host (any execution_mode) → forced subprocess.

### `fan_out_ask` (modified)

Signature unchanged. Behavior:
- `execution_mode='instruction'` → enqueues N `awaiting_caller` jobs (one per target), returns a single packet that batches all targets. Caller spawns N parallel Agents.
- `execution_mode='subprocess'` → existing v25 behavior (parallel subprocess fanout + optional synthesis).
- Remote targets in instruction mode → those individual targets fall back to subprocess (the others stay instruction).

### `record_delegation_result` (NEW)

```python
@mcp.tool()
def record_delegation_result(
    job_id: str,
    status: Literal["completed", "failed"],
    output: str | None = None,
    error: str | None = None,
    duration_ms: int = 0,
    tokens_used: int | None = None,
) -> str:
    """Caller reports the result of an instruction-mode delegation.

    Validates the job exists and is currently `awaiting_caller`. Transitions
    to `completed` or `failed`, fires the standard completion fan-out
    (SSE, FleetQ Bridge publisher, Event/Condition waiters). Idempotent on
    terminal state: a second call with a different result is rejected.
    """
    ...
```

Returns:
- `"recorded {job_id} as completed/failed (duration_ms=N, tokens=N)"` on success
- `"Error: job {job_id} not found"` or `"Error: job {job_id} already in terminal state {status}"` on validation failure

### `get_delegated_task` (modified)

For `awaiting_caller` jobs, returns the original instruction packet so a caller that lost track can re-execute. Same shape as `delegate_task`'s return.

## State Machine

```
                    enqueue_instruction
                            │
                            ▼
                  ┌──────────────────┐
                  │ awaiting_caller  │  ←── (instruction mode entry)
                  └─────┬────────────┘
                        │
              ┌─────────┴────────┐
              ▼                  ▼
   record_delegation_result   orphan sweep
       (status=completed)     (after timeout)
              │                  │
              ▼                  ▼
        ┌─────────┐         ┌─────────┐
        │completed│         │ failed  │
        └─────────┘         └─────────┘

                       enqueue (legacy)
                            │
                            ▼
                       ┌─────────┐
                       │ queued  │  ←── (subprocess mode entry)
                       └────┬────┘
                            │ worker.claim_next_queued
                            ▼
                       ┌─────────┐
                       │ running │
                       └────┬────┘
                            │ worker.complete / .fail
                            ▼
                     completed | failed
```

## Backwards Compatibility

- **Legacy callers** using v25 `delegate_task` will receive the new instruction packet on the first call after upgrade. The packet is human-readable markdown — they can read it and follow manually, or ignore it (orphan sweep). Operators who depend on the legacy behavior set `[delegate] execution_mode = "subprocess"` in their TOML and v25 behavior returns unchanged.
- **JobStore schema** migrates idempotently on `JobStore.__init__`. Existing rows get `execution_mode = 'subprocess'` (their actual provenance), no data loss.
- **Async workers** continue to claim only `queued` rows — `awaiting_caller` rows are invisible to them by design.
- **Completion fan-out** (SSE, Bridge publisher, Event/Condition waiters) fires identically for both modes — they all go through `_fire_completion(job_id)`.
- **FleetQ Bridge contract** unchanged. The bridge endpoint `/api/v1/harbormaster/job-completed` consumes the same payload schema regardless of which mode populated the row.
- **API surface preservation**: every existing MCP tool retains its v25 signature. Only one new tool added.

## Risk Assessment

| Risk | Mitigation |
|---|---|
| Caller doesn't recognize the packet → orphan jobs | Orphan sweep with configurable TTL (default 1h); `failed` with clear error |
| Caller calls `record_delegation_result` twice | Idempotent guard rejecting second-write-with-different-result |
| Caller crashes mid-Agent → `awaiting_caller` lingers | Orphan sweep cleans it up |
| Operator runs SSH and forgets to override mode | Auto-fallback: SSH targets always go through subprocess regardless of `execution_mode` |
| Test fragility from new state | New tests + every existing test that asserts `status` re-checked |
| Migration races: two harbormaster processes opening db | SQLite WAL + idempotent ALTER TABLE — same pattern as v22.0.1 max_turns migration |

## Performance

Instruction mode is **strictly faster** than subprocess on the harbormaster side:
- No subprocess fork/exec
- No LLM API round-trip
- No SSE streaming
- Just one INSERT into `delegated_jobs` and return the packet string

Approximate latency: `delegate_task` in instruction mode returns in **<10ms** (one SQLite write + string formatting). v25 subprocess mode: median 4 minutes.

The work shifts to the caller's process, where `Agent()` invocation has its own latency profile. Net: same user-perceived wall time, but the cost lives on the subscription pool instead of the programmatic credit.

## Rollout

Single tag `v26.0.0`. No staged rollout — the behavior change is opt-out (via config) and operationally safe (orphan sweep handles unrecognizing callers).

Post-deploy verification checklist (operator):
1. `harbormaster-mcp` restarts cleanly with new code.
2. `delegate_task(name="<test-project>", task="say hello", deliverable="acknowledge")` returns an instruction packet (not actual LLM output).
3. Caller assistant spawns `Agent()` per packet, gets answer, calls `record_delegation_result`.
4. `/jobs` page shows the job moved through `awaiting_caller` → `completed`.
5. FleetQ Bridge (if armed) shows broadcast event on completion.
6. `[delegate] execution_mode = "subprocess"` in TOML reverts behavior to v25 in one restart.

# Test Plan — v26.0.0 Orchestrator-in-the-loop Pivot

**Date**: 2026-05-14
**Phase**: Plan
**Status**: Approved
**Companion**: `design-v26-orchestrator-in-the-loop.md`, `architecture-v26-orchestrator-in-the-loop.md`

## Baseline

v25.0.0 has **1041 unit tests + 1 skip** passing, `mypy --strict` clean, `ruff` clean, 8 CI jobs green. Any v26 change that regresses this baseline is a release blocker.

## New Test Files

### `tests/unit/test_v26_instruction_backend.py` (~10 tests)

1. `test_instruction_backend_local_returns_packet_with_marker` — `ask_local` returns a string containing `HARBORMASTER_INSTRUCTION_V1`.
2. `test_instruction_backend_local_creates_awaiting_caller_row` — JobStore row is created with `status='awaiting_caller'`, `execution_mode='instruction'`.
3. `test_instruction_backend_local_packet_contains_job_id` — packet contains the row's job_id.
4. `test_instruction_backend_local_packet_contains_cwd` — packet contains the resolved project cwd.
5. `test_instruction_backend_local_packet_contains_full_prompt` — packet embeds the input prompt.
6. `test_instruction_backend_local_packet_contains_max_turns_hint` — packet contains the max_turns hint.
7. `test_instruction_backend_remote_raises_error` — `ask_remote` raises `BackendError(code="instruction_no_remote")`.
8. `test_instruction_backend_duration_ms_is_small` — packet build completes in <100ms (no LLM call).
9. `test_instruction_backend_model_hint_propagated` — `model="haiku"` shows up in the packet's agent-options JSON.
10. `test_instruction_backend_packet_json_is_parseable` — extracted JSON block parses cleanly.

### `tests/unit/test_v26_record_result.py` (~10 tests)

1. `test_record_result_completed_transitions_status` — `awaiting_caller` → `completed`, output persisted.
2. `test_record_result_failed_transitions_status` — `awaiting_caller` → `failed`, error persisted.
3. `test_record_result_unknown_job_returns_error` — non-existent job_id returns `Error: ...not found`.
4. `test_record_result_already_terminal_idempotent_same_status` — second call with same status returns success message.
5. `test_record_result_already_terminal_conflicting_status_rejected` — second call with different status returns an error.
6. `test_record_result_fires_event_for_wait_for_job` — `wait_for_job` waiter unblocks after `record_delegation_result`.
7. `test_record_result_fires_inbox_condition` — `wait_for_inbox` waiter unblocks too.
8. `test_record_result_persists_tokens_used` — `tokens_used=12345` stored on row.
9. `test_record_result_persists_duration_ms` — `duration_ms` stored on row.
10. `test_record_result_subprocess_mode_job_still_works` — calling `record_delegation_result` on a `queued` legacy row is rejected (mode mismatch).

### `tests/unit/test_v26_delegate_instruction.py` (~7 tests)

1. `test_delegate_sync_instruction_returns_packet` — sync call returns marker, no `claude -p` spawned (verified via `ClaudeBackend` mock not called).
2. `test_delegate_sync_subprocess_unchanged` — opt back to `subprocess` mode → existing v25 sync behavior, mock backend invoked.
3. `test_delegate_async_instruction_returns_handle_and_packet_via_get` — async call returns `queued JOB_ID`; `get_delegated_task` returns the packet.
4. `test_delegate_async_subprocess_unchanged` — opt back → existing v22+ async worker behavior.
5. `test_delegate_ssh_host_forces_subprocess_in_instruction_mode` — `host='friday'` config triggers fallback even when `execution_mode='instruction'`.
6. `test_delegate_writes_packet_marks_allow_writes` — `allow_writes=True` is encoded in packet metadata.
7. `test_delegate_max_turns_propagates_to_packet` — `max_turns=80` shows up in packet.

### `tests/unit/test_v26_ask_instruction.py` (~5 tests)

1. `test_ask_instruction_returns_packet` — returns marker, no backend call.
2. `test_ask_subprocess_unchanged` — opt-back unchanged.
3. `test_ask_remote_host_forces_subprocess` — SSH falls back.
4. `test_ask_instruction_creates_awaiting_caller_row` — JobStore row exists with `tool='ask'` discriminator (or check via packet metadata).
5. `test_ask_packet_has_500_word_suffix` — the existing 500-word constraint propagates to the prompt embedded in the packet.

### `tests/unit/test_v26_fan_out_instruction.py` (~5 tests)

1. `test_fan_out_instruction_returns_batch_packet` — single packet containing N targets.
2. `test_fan_out_instruction_creates_n_rows` — N `awaiting_caller` rows persisted.
3. `test_fan_out_mixed_local_remote_splits_modes` — local targets get instruction, remote targets get subprocess inline (verified by mock).
4. `test_fan_out_subprocess_unchanged` — opt-back unchanged.
5. `test_fan_out_synthesize_flag_in_instruction_mode` — `synthesize=True` is encoded in the packet so the caller knows to do the synthesis pass after collecting per-target answers.

### `tests/unit/test_v26_schema_migration.py` (~3 tests)

1. `test_pre_v26_db_migrates_to_add_execution_mode_column` — open a v25-schema db; `execution_mode` and `tokens_used` columns appear; existing rows get `'subprocess'`.
2. `test_v26_db_open_idempotent` — open new schema twice, no errors.
3. `test_status_awaiting_caller_in_valid_statuses` — sanity check.

### Sweep test addition

In `tests/unit/test_jobs_store.py` (existing file):

- `test_recover_orphaned_awaiting_caller_after_timeout` — `awaiting_caller` row older than configured TTL gets `failed` with error="caller never recorded result".

## Regression Tests Touched (existing files)

- `tests/unit/test_delegate.py` — every `delegate_task` test parameterised by `execution_mode` (or extended with subprocess fixture). Existing assertions stay true under `execution_mode='subprocess'`. Add a parallel test sometimes for instruction mode.
- `tests/unit/test_ask.py` — same pattern.
- `tests/unit/test_fan_out.py` — same pattern.
- `tests/unit/test_jobs_store.py` — assert `awaiting_caller` is recognized.
- `tests/unit/test_jobs_wait.py` — `awaiting_caller` doesn't unblock `wait_for_job`; `completed` (via record_delegation_result) does.
- `tests/unit/test_v15_precommit_integration.py` — config doc parity check passes for new knobs.

## Acceptance Criteria

- [ ] **Existing tests**: 1041 unit tests + 1 skip, all pass.
- [ ] **New tests**: ≥40 new unit tests, all pass.
- [ ] **mypy --strict**: clean across `src/harbormaster`.
- [ ] **ruff**: clean.
- [ ] **Config doc parity** (`scripts/check_config_doc_parity.py`): passes.
- [ ] **Smoke**: `harbormaster-mcp` boots without errors against a brand-new (empty) db AND a v25 db copy.
- [ ] **Smoke**: `delegate_task` in instruction mode returns a packet recognised as `HARBORMASTER_INSTRUCTION_V1`; the corresponding row is `awaiting_caller`.
- [ ] **Smoke**: `record_delegation_result` flips it to `completed`, fires SSE, fires inbox-condition waiter.
- [ ] **Smoke**: opt-back `execution_mode='subprocess'` makes one round-trip of `delegate_task` go through the legacy path (verified by inspecting that the JobStore row has `execution_mode='subprocess'`).

## How We'll Run It

```shell
cd /Users/katsarov/htdocs/harbormaster
.venv/bin/python -m pytest tests/unit -x --tb=short
.venv/bin/python -m pytest tests/unit/test_v26_*.py -v
.venv/bin/python -m mypy --strict src/harbormaster
.venv/bin/python -m ruff check src/ tests/
.venv/bin/python scripts/check_config_doc_parity.py
```

If `.venv` doesn't exist, `python -m venv .venv && .venv/bin/pip install -e ".[dev]"`. CI uses the same commands.

## Out of Scope for v26 Tests

- End-to-end test that actually launches `claude` and verifies the operator's subscription pool was charged (no programmatic way to verify Anthropic billing from inside the test suite — manual operator validation only).
- Bridge round-trip live test (covered by existing v24 bridge integration tests, which are not exercised in unit test CI).
- UI/dashboard render parity tests for the new `execution_mode` column (Jinja templates have minimal coverage today; one source-grep helper test is enough to catch regressions).

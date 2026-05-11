# Sprint Retro — Harbormaster v21.0.6 (patch)

**Released:** 2026-05-11
**Type:** Patch — unified activity logging across MCP transports
**Branch flow:** Directly on `main`

## Why this patch exists

Operator report against v21.0.5: the dashboard's **Activity** tab
(`/#tab=activity`) and the network page's **Timeline** tab
(`/network#tab=timeline`) were both empty even though tool calls
were happening (stdio Claude sessions actively asking projects).

Diagnosis:

- Both tabs read from `/api/network/events`, which queries the
  `mcp_calls` table in `~/.harbormaster/network_log.db`.
- `mcp_calls` had **0 rows** even though `qa_log` (the trajectories
  source) had 7 rows of real Q&A history.
- Root cause: `network_log.record()` was only called from the UI's
  HTTP `/mcp/{server}` routing handlers (`routes.py:3615/3742/3750/3756`).
  Stdio MCP sessions land directly in the FastMCP tool registry
  without ever crossing the HTTP layer, so they wrote to `qa_log`
  (via `_maybe_record_qa`) but skipped `network_log` entirely.

The activity feed promised "Ask any project something via your MCP
client and the call will appear here in real-time" but only delivered
on HTTP. The operator's stdio activity was invisible.

## Fix shipped

### Mirror Q&A writes into `network_log`

`src/harbormaster/tools/_helpers.py::_maybe_record_qa`: after the QA
store insert succeeds, the same call is mirrored into the UI's
network_log via a lazy import:

```python
try:
    from harbormaster.ui.network_log import (
        current_caller_project,
        network_log,
    )

    network_log.record(
        caller=current_caller_project() or "operator",
        target=project_name,
        tool=tool,
        status="ok",
        question_preview=prompt,
        duration_ms=duration_ms,
    )
except ImportError:
    pass   # stdio-only setup without [ui] → no-op
except Exception:
    logger.exception("network_log mirror failed; swallowing")
```

The lazy import preserves the v1's invariant that `harbormaster.tools`
never hard-requires `[ui]` — pure stdio MCP users without the UI extra
installed still get a working tool dispatcher; the mirror simply
no-ops on ImportError.

Failures inside `record()` are also swallowed — instrumentation must
never break the hot path of a tool dispatch.

### Empty-state copy refresh

`dashboard.html` Activity-tab empty state used to read:

> Ask any project something via your MCP client and the call will
> appear here in real-time.

After v21.0.6 this is no longer transport-specific. New copy:

> Ask any project something via any MCP client (stdio, HTTP, SSE) —
> the call lands here in real-time.

## Architecture note

`network_log` is now the single canonical "MCP call happened" log
across transports. `qa_log` remains the prompt/answer recall surface
(for `/api/recall`, `/api/trajectories`, and the auto-grounding hot
path); `network_log` is the activity-feed / timeline / per-project
budget surface.

Both writes are best-effort and independent — `qa_log` failure
doesn't block `network_log` and vice versa, and either failure logs
WARNING without breaking the tool dispatch.

## Verification

- `ruff check src/ tests/` — clean
- `mypy --strict src/harbormaster/` — clean (59 source files)
- `pytest tests/` — **1909 passed** (+4 for `test_qa_network_log_mirror.py`),
  1 skipped, 0 failed
- New tests pin:
  - Happy path: one `_maybe_record_qa` call → one mcp_calls row
  - 200-char preview cap honoured for long prompts
  - `[history]` disabled → no mirror (skipped at the gate)
  - `network_log.record` raising → swallowed, no propagation

## Chain status

Still HALTED. v21.0.6 is the sixth operator-initiated patch in the
2026-05-11 audit cycle.

## Lesson captured

Activity surfaces that promise "any MCP call" must record at the
**tool-dispatch layer**, not at the **transport layer**. Transport-
specific logging (HTTP-direct only) silently misses stdio/SSE clients
and makes operators think the feature is broken.

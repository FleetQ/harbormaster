# Sprint Retro — Harbormaster v21.0.7 (patch)

**Released:** 2026-05-12
**Type:** Patch — debug forensics on backend failures
**Branch flow:** Directly on `main`

## Why this patch exists

Operator report on 2026-05-12: "agents tell me harbormaster MCP times
out, but I have no way to investigate which project / host / why".

Diagnosis (read against v21.0.6):

- Five distinct timeout layers exist (`backends/claude.py`,
  `backends/codex.py`, `ssh.py`, the SSE heartbeat, `[backends.*]
  timeout_local`). Each raises `BackendError(code="timeout")` with a
  message like `"timeout: claude -p exceeded 60s"` and nothing else.
- `run_backend` (the sync orchestrator in `tools/_helpers.py`) catches
  it and returns the literal string `f"Error: {e}"`. The MCP agent
  sees that string. Nothing identifies which project failed, how long
  it actually ran, or what stage (connect vs total).
- No `logger.error` / `logger.warning` was emitted anywhere in
  `backends/` for these failures — verified by ripgrep across both
  backend modules.
- `_maybe_record_qa` (the unified-activity hook from v21.0.6) is only
  invoked on the success path. Timeouts and other failures never
  reach the `network_log`, so the dashboard Activity / Timeline tabs
  silently miss them — the same v21.0.6 lesson re-played in the
  opposite direction.
- `stderr` from the killed subprocess (often the most useful signal —
  rate-limit JSON, auth errors) was read by the `finally` block in
  streaming paths only, and even there the bytes were not attached
  to the `BackendError` message.

Net effect: the operator has the v21.0.6 success-side activity feed
working, but failure forensics are still completely opaque.

## Fix shipped

### 1. `_record_backend_failure` helper + correlation id

New private helper in `tools/_helpers.py`:

- Generates an 8-char hex correlation id (`secrets.token_hex(4)`).
- Emits one structured WARNING log line:
  `backend_failure cid=<id> tool=<tool> project=<name> host=<host>
  code=<code> elapsed_ms=<ms> message=<truncated str>`.
- Mirrors the failure into `network_log` with `status="error"`,
  `target=project_name`, `tool=label_prefix`, `duration_ms=elapsed_ms`.
  Uses the same lazy-import pattern as v21.0.6 so pure-stdio
  installations without the `[ui]` extra still no-op cleanly.
- Best-effort: a crash inside the helper is logged at exception level
  but never propagated.

### 2. `run_backend` enriched error string

The agent-facing string changes from
`"Error: timeout: claude -p exceeded 60s"`
to
`"Error: ask(name='X', host='Y') failed after 60001 ms [cid=ab12cd34]
— code=timeout: timeout: claude -p exceeded 60s (elapsed=60.0s)"`.

The literal `Error:` prefix is **preserved** — `fan_out.py:175`
filters target answers on it and external MCP agents historically
pattern-match on it too. The correlation id, elapsed_ms, tool +
project + host, and stable error code all land *after* the colon so
the prefix-based contract still holds.

### 3. Mid-stream SSE failure mirrored too

`ui/routes.py::_emit_chunks_then_result` catches `BackendError` mid-
iteration and yields an `error` SSE event. v21.0.7 also calls
`_record_backend_failure` from that same except block and attaches
the `correlation_id` + `elapsed_ms` fields onto the event payload so
browser consumers + the dashboard Activity tab see the same id.

### 4. Backend timeout messages enriched

`backends/claude.py` and `backends/codex.py` — every
`subprocess.TimeoutExpired` and `SshTimeoutError` catch now includes:

- `elapsed=<seconds>` — distinguishes "ssh never connected" (elapsed
  ≈ `connect_timeout`) from "remote claude hung" (elapsed ≈
  `total_timeout`).
- `stderr_tail=<repr of last 300 bytes>` — for local timeouts, the
  partial stderr that the subprocess emitted before being killed
  (claude -p often writes API-rate-limit / auth-failure JSON there).
- For SSH timeouts, the configured `connect_timeout=<s>` and
  `total_timeout=<s>` are surfaced so the operator can tell at a
  glance which knob to tune.

## Architecture note

This patch reuses the tool-dispatch-layer logging rule established
in v21.0.6 (see memory `v21.0.3-v21.0.6-patch-arc`): activity
surfaces — including *failure* surfaces — must hook at the tool
dispatcher, not at the HTTP transport. v21.0.6 fixed the success
side; v21.0.7 closes the failure side. The two are now symmetric.

Distinguishing data surfaces, updated for v21.0.7:

| Surface | Source | Lifecycle | Now records failures? |
|---|---|---|---|
| `qa_log` (qa_local.db) | tool layer | persistent | No — success only by design (it's a Q&A recall store) |
| `mcp_calls` (network_log.db) | tool layer (v21.0.6) + sync run_backend failure path (v21.0.7) + mid-stream SSE failure (v21.0.7) | persistent | **Yes** — `status="error"` rows since v21.0.7 |

## Verification

- `ruff check src/ tests/` — clean (one `try/except/pass` flagged in
  routes.py; resolved by switching to `contextlib.suppress(Exception)`)
- `mypy --strict src/harbormaster/` — clean (59 source files)
- `pytest tests/` — **1916 passed** (+7 for the new
  `test_run_backend_failure_logging.py`), 1 skipped, 0 failed
- Existing brittle assertions in `tests/integration/test_e2e_fake_claude.py`
  that checked `out.startswith("Error:")` continue to hold — the
  `Error:` prefix contract was preserved deliberately.

New tests pin:

- Enriched error string contains `cid`, `tool(name, host)`,
  `failed after N ms`, `code=<code>`, and the original message.
- The literal `Error:` prefix is preserved (load-bearing contract).
- The `mcp_calls` table gets one row per failure with `status="error"`.
- One WARNING line per failure with `cid=<id>` for grep correlation.
- Remote-host failures surface `host=<actual host>` (not `local`).
- `network_log.record()` crashing inside the failure path doesn't
  propagate — the agent still receives the enriched error string.
- Correlation id format is exactly 8 hex chars, unique per call.

## Operator playbook (new in v21.0.7)

When an agent reports a harbormaster timeout, the operator can now:

1. Look at the `Error: ... [cid=<id>] ...` string the agent surfaces.
2. `grep cid=<id> ~/.harbormaster/logs/*` (or journald / wherever the
   harbormaster process logs go) for the matching WARNING line.
3. Open the dashboard Activity tab — the failed call appears with
   `status="error"` and the same target/tool/duration_ms.
4. Inspect the surfaced `elapsed=<s>`, `connect_timeout=<s>`,
   `total_timeout=<s>`, `stderr_tail=<...>` fields to localise the
   failure (ssh connect vs remote claude hang vs API rate-limit).

## Chain status

Still HALTED on the v21 base. v21.0.7 is the seventh operator-
initiated patch since v21.0.0.

## Lesson captured

Tool-dispatch-layer logging is symmetric: both **success** and
**failure** events must hook the same layer. v21.0.6 fixed
"successful calls are invisible on stdio"; v21.0.7 fixed "failed
calls are invisible everywhere". The same instrumentation pattern
applies — lazy `[ui]` import, swallow on ImportError, swallow on
record() exceptions, never break the user-facing return path.

Surfacing a short correlation id in user-facing error strings is
cheap (8 hex chars) and turns previously-opaque failures into
greppable forensic anchors.

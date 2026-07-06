# Sprint Retro — Harbormaster v27.1.2

**Date:** 2026-07-06
**Theme:** MCP server-level instructions + long-poll timeout guidance. `build_server`
now passes FastMCP `instructions` (was none) orienting the client on the
ask/delegate→await/recall workflow and, critically, on the interactive-client
timeout pitfall: `await_delegated_task`/`await_inbox` block up to 900s by default,
but Claude Desktop/claude.ai expire a tool call after a few minutes → "request may
have expired". Instructions + docstrings tell the model to pass a short
`timeout_seconds` (60-120) and re-call on interactive clients. Motivated by a real
Desktop `await_inbox` failure.

## What landed

### `harbormaster` (this repo)

| SHA | Subject |
|-----|---------|
| `0d30036` | feat: MCP server instructions + long-poll timeout guidance (#35) |

## Capabilities (this sprint)

### 1 · Server-level `instructions` on `build_server`

`build_server` previously constructed `FastMCP("harbormaster")` with no
`instructions` block, so the calling client had zero built-in orientation on the
delegate→await workflow. A new `SERVER_INSTRUCTIONS` constant is now passed to
`FastMCP(..., instructions=SERVER_INSTRUCTIONS)`, summarizing `ask_project` /
`fan_out_ask` / `delegate_task` / `await_delegated_task` / `await_inbox` /
`recall_pending_results` / `recall_qa` in a few lines, injected into the client's
context once per session.

### 2 · Long-poll timeout guidance surfaced in instructions + docstrings

The same block — and matching docstring additions on `await_delegated_task` and
`await_inbox` in `tools/await_jobs.py` — calls out the failure mode explicitly:
these tools block up to `timeout_seconds` (default 900s), but interactive clients
(Claude Desktop, claude.ai) can only hold a tool call open for a few minutes before
the result window expires, producing "request may have expired" /
`side_channel_waiting_key_absent`. The guidance tells the model to pass a short
`timeout_seconds` (60-120) and re-call to keep waiting on those clients, and that
`timed_out: true` / status `queued`|`running` means "nothing yet, re-call" — not an
error. No behavior change; purely doc/instructions surface.

## Real numbers

- 1/1 items shipped (single-issue doc release, no prior-sprint action-item list to
  reconcile against)
- 1 PR opened / merged (#35, squash-merged)
- New tests: 1 file, `tests/unit/test_server_instructions.py` (23 lines)
- Test suite: 2192 passed, 1 skip (full suite, CI matrix macOS/Ubuntu ×
  py3.11/3.12/3.13 all green)
- Lint / type-check: `ruff` clean, `mypy --strict` clean
- Backwards-incompatible changes: 0 — docs/instructions only, no wire or behavior
  change

## What worked

- **Field failure over speculation.** As with the v27.1.x backoff fixes, a real
  Claude Desktop failure (`await_inbox` blocked ~4 min on the 900s default, tool
  result could no longer be submitted) grounded the fix in an actual observed
  failure mode rather than a hypothetical.
- **Docs-only patch, minimal blast radius.** The change touches only a docstring
  constant and two docstrings — no runtime behavior differs, keeping the release
  safe to ship as a same-day patch after the prior backoff fix.

## What to change / next

- **No test currently asserts an interactive client actually reads and obeys the
  new instructions.** `test_server_instructions.py` checks the instructions string
  is present and non-empty on the built server, but nothing exercises a client
  picking a short `timeout_seconds` because of it — that's inherently
  client-behavior, outside this repo's test boundary, but worth flagging so a
  future regression (e.g. instructions silently dropped) isn't caught only by
  another field failure.

## Action items for the next sprint (v27.2.0 / week 1)

1. **Add a live smoke test asserting backoff behavior under a forced 401.**
   Carried over from v27.1.1 — existing smoke jobs cover the happy-path bridge
   register; none exercise a persistent-auth-failure scenario end-to-end the way
   the unit tests do at the unit level.
2. **Carry over from v27.1.0: add a live stdio-transport smoke test to CI**
   asserting the *absence* of bridge registration/heartbeat traffic when
   `--transport stdio` is used.
3. **Carry over from v27.1.0: document `bridge_in_stdio` in the operator config
   reference** with a worked example for the single long-lived stdio host use
   case.
4. **Consider a `clientInfo.name`-keyed default `timeout_seconds`** so
   `await_delegated_task`/`await_inbox` could pick a short default automatically
   for known-interactive clients instead of relying solely on the model reading
   the instructions/docstring guidance.

## Out-of-scope (still)

- Plugin-registered third-party orchestrator adapters (seam present since
  v27.0.0, not shipped) — no external consumer request yet.
- Antigravity CLI (Gemini CLI successor) adapter verification — mapped via
  substring to the `gemini` adapter as a placeholder; needs empirical
  confirmation the subagent contract carries over.
- Empirical `clientInfo.name` mapping table per CLI — deferred until more
  non-Claude clients are observed in the field.

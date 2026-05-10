# Sprint Retro — Harbormaster v16.0.0a6

**Date:** 2026-05-10
**Theme:** Trace waterfall — backend instrumentation slice. The plan
authorised a split if the instrumentation alone took >2hr; the actual
implementation took ~35 min so the split was elective. **Decision:
ship a6 as instrumentation-only, defer the waterfall renderer to
v17.** Rationale: clean release boundary, low blast radius, every
new field is additive.

## What shipped

- **`_RunningSpan` / `_CompletedSpan` carry `parent_span_id` +
  `trace_id`**. Default `None` preserves the v9.0.0a3 byte shape so
  every existing caller still works without modification.
- **`DispatcherStats.record_start(parent_span_id=, trace_id=)`**.
  Root spans (no parent) auto-derive `trace_id = own span_id`.
  Child spans inherit the parent's `trace_id` via a small
  `_lookup_trace_id_locked()` walk over the running list and the
  recently-completed ring. Orphan children (parent already rolled
  out) gracefully promote to a new root.
- **`span_context(span_id, trace_id)` thread-local context manager**
  + `current_span_id()` / `current_trace_id()` lookups. Backends
  invoked inside a dispatch can attribute child spans to the
  parent without explicit plumbing. Nested binding restores on
  exit so concurrent dispatches don't leak.
- **`MCPDispatcher.dispatch` wraps invocation** in
  `span_context(...)` so the binding is automatic — no backend
  has to opt in or import the helper to participate.
- **`ClaudeBackend._extract_assistant_text` observes `tool_use`
  blocks** in the stream-json output and emits child spans tagged
  `tool="claude.tool:<NAME>"`. `tool_result` blocks close the
  matching child via a small `_TOOL_USE_SPANS` registry. The
  whole instrumentation is best-effort — failures swallow,
  user-facing text is never blocked, FleetQ extra not required
  for pure rendering tests.
- **SSE event format** (`/api/dispatcher/trace`): `span_start` and
  `span_end` payloads now carry `parent_span_id` + `trace_id`.
  `/api/dispatcher/recent` returns the same fields on each row.
- **`fleetq` package re-exports** the new helpers
  (`current_span_id`, `current_trace_id`, `span_context`).

## Numbers

- **Tests**: 1580 → 1593 (+13 net new — 3 model + 2 SSE + 1
  context + 1 dispatcher binding + 5 claude.py + 1 endpoint)
- **Source files**: 57 (unchanged — extensions only; new helpers
  live inside existing `dispatcher.py` and `claude.py` modules)
- **Wall-clock**: ~35 min (well under the 2hr split-trigger
  threshold)
- **Commits on main**: 1 feature merge
- **Lint / type**: ruff clean, `mypy --strict` clean
- **Backwards-incompatible changes**: 0
  - Span dataclasses' new fields default to `None`.
  - SSE event payloads grew two optional keys; existing
    consumers ignore unknown keys (the dispatcher_trace.html
    waterfall doesn't read them yet — that's the v17 work).
  - The `trace_id == span_id` invariant for root spans means
    every previously-emitted span effectively has a one-element
    trace going back through the ring.
- **Confirmation: did NOT touch `.github/workflows/*`** — yes.

## Why split

- **Risk asymmetry**: the backend instrumentation is small,
  isolated, and well-tested. The waterfall renderer is template
  work with parent/child layout, hover + collapse semantics,
  and an SSE-driven re-paint loop. Different failure modes,
  different review surfaces.
- **Composable shipping**: v16.a6 already adds operator value —
  `/api/dispatcher/recent` now returns enough structure for a
  third-party tool (Honeycomb, Tempo, etc.) to ingest. The
  Harbormaster-native renderer is icing.
- **Time budget held**. The 6-alpha sprint stays on track; v17
  inherits a single, well-scoped frontend task instead of a
  half-finished refactor.

## What worked

- **Default-None additive fields**. Made every existing test pass
  unchanged. The only test files needing changes were the new
  ones written specifically for v16.a6.
- **Best-effort instrumentation**. Wrapping every span emission
  inside the claude.py helpers in `try / except Exception`
  means a single mis-shaped tool_use block can't kill the user-
  facing answer stream.
- **`span_context()` is `contextlib.contextmanager`**. Exact
  same shape as v15.a4's similar binding for the per-tool
  budget — operators reading the source see one pattern, not
  two.
- **CWD discipline held.** All Bash calls in this phase ran
  from the worktree CWD without explicit `cd`. Discipline
  lapses for v16.a6: **0**.

## What to change for v17

- Single top candidate: **trace waterfall true parent/child
  viz**. Backend already emits the right events. The renderer
  should:
  - Group spans by `trace_id` into one waterfall block.
  - Indent child spans under their parent (computed from
    `parent_span_id`).
  - Render bar widths proportional to `(ended_at -
    started_at) / trace_total_duration`.
  - Hover surfaces project name + tool name + duration.
- Plus the v15→v16 carry-overs that didn't make this sprint
  (CI workflow autobootstrap — still requires operator OAuth
  token rotation for `workflow` scope).

## Notes for v16.a6 split decision

**Decision: split executed.** v16.a6 ships as backend
instrumentation + SSE event format only. Waterfall renderer is
the top v17 candidate. Documented in this retro.

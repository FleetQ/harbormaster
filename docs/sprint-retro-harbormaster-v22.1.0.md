# Sprint Retro — Harbormaster v22.1.0

**Date:** 2026-05-12
**Theme:** Blocking awaits replace polling. ``await_delegated_task``
and ``await_inbox`` MCP tools let an agent park on a tool call until
the JobWorker fires a wake-up — no more per-agent polling decisions
about interval and timeout. Pull → push within MCP, no new protocol
or client-side support required.

## Triggering observation

An agent operator pointed out: "Shouldn't the agent be notified when
ready instead of having to check?". v22.0.x is purely pull — caller
spends thinking cycles deciding when to poll
`get_delegated_task` / `recall_pending_results`. MCP has notification
machinery (``notifications/resources/updated``), but reliable surfacing
to the model side depends on client implementation. The minimum-
viable, universally-supported fix is a tool that holds the request
open and returns the moment the worker finishes.

## What landed

| File | Subject |
|---|---|
| `src/harbormaster/jobs/store.py` | per-job ``Event`` + per-inbox ``Condition`` + ``add_subscriber``/``remove_subscriber`` hook (v22.2.0 forward) + ``wait_for_job`` + ``wait_for_inbox`` + ``_fire_completion`` plumbing |
| `src/harbormaster/tools/await_jobs.py` | new — ``await_delegated_task`` and ``await_inbox`` MCP tools |
| `src/harbormaster/tools/__init__.py` | registers the new pair |
| `tests/unit/test_jobs_wait.py` | new — 11 store-level tests covering Event/Condition wakeups, timeouts, ``since`` filter, subscriber crash isolation |
| `tests/integration/test_jobs_await_e2e.py` | new — 6 fake_claude e2e tests (await unblocks on completion, timeout shape, fan-out fires on first landing, concurrent waiters both wake via notify_all) |
| `tests/unit/test_tools.py` | asserts new tools in registry |
| `README.md` | Ten → Twelve MCP tools; await rows added |
| `src/harbormaster/__init__.py` | 22.0.1 → 22.1.0 |
| `docs/sprint-retro-harbormaster-v22.1.0.md` | this file |

## Capabilities

### MCP surface

- ``await_delegated_task(job_id, timeout_seconds=900)`` — blocks
  until the job lands. Returns immediately if already terminal. On
  timeout, returns the row with whatever status it has (``"queued"``
  or ``"running"``) — caller can re-call to extend the wait. Same
  return shape as ``get_delegated_task``.
- ``await_inbox(inbox_id, timeout_seconds=900, since=None)`` — blocks
  until ANY job in the inbox lands. Returns ``{inbox_id, results,
  timed_out}``. ``since`` (unix seconds) filters completions already
  drained, so a fan-out batch can be processed
  "wake → drain first → wake on next → drain next → ..." without
  re-seeing finished jobs.

Default ``timeout_seconds=900`` (15 min) matches the upper end of
the v22.0.1 ``max_turns`` guideline. Caller adjusts per task shape.

Both tools fall back to the polling/peek surface — the await is an
optimisation, not a replacement. ``recall_pending_results`` still
exists and is the only way to ``mark_read`` consumed jobs.

### Store-level primitives

- ``JobStore.wait_for_job(job_id, timeout_seconds)`` —
  ``threading.Event``-backed. Sticky one-shot means it's safe for the
  worker to ``set()`` before any waiter calls ``wait()``.
- ``JobStore.wait_for_inbox(inbox_id, timeout_seconds, since)`` —
  ``threading.Condition.notify_all()``. Multiple waiters all wake
  on a single completion. Race between "check pending → wait" closed
  by acquiring the Condition before the initial check.
- ``add_subscriber(callable)`` — v22.2.0 forward hook. Subscribers
  fire on the worker thread after waiters are notified, with the
  final ``Job`` view. Exceptions swallowed (pattern from v21.0.6/7
  instrumentation rule).

## Numbers

- 9 files (5 new). ~470 LOC (mostly tests).
- 1981 → 1998 tests (+17). mypy --strict clean (67 source files).
  ruff src/ tests/ clean.

## Design notes

### Acquire Condition BEFORE the initial check

The classic CV pattern. ``wait_for_inbox`` does::

    with cond:
        existing = _matching()
        if existing:
            return existing
        cond.wait(timeout=timeout_seconds)
    return _matching()

Acquiring ``cond`` before reading the inbox closes the race where a
job completes between the read and the wait. The worker's
``_fire_completion`` also acquires the same condition before
``notify_all()`` — so the worker either fires BEFORE the waiter
acquires (and the waiter's initial check sees the new state) or
AFTER the waiter is parked on ``cond.wait()`` (and the notify wakes
it). No silent miss.

### Sticky Event for the single-job case

For ``wait_for_job``, ``threading.Event`` semantics are stickier than
``Condition``: once ``set()`` is called, subsequent ``wait()`` calls
return immediately. Means the worker can ``set()`` before any waiter
arrives — the next waiter still gets the wakeup. No race window to
worry about.

### Subscribers run AFTER waiters, on the worker thread

``_fire_completion`` fires per-job Event → per-inbox Condition →
subscribers, in that order. Subscribers run on the worker thread so
a slow subscriber blocks the next job claim. That's acceptable for
v22.2.0's resource-subscription use case (notifications are cheap)
but worth noting for future subscribers that might do expensive
work — they should defer to a thread pool themselves.

### Exception isolation on subscribers

Pattern carried from v21.0.6 + v21.0.7: instrumentation must never
break the hot path. Subscriber exceptions are silently suppressed via
``contextlib.suppress(Exception)``. A regression-guard test
(``test_subscriber_callback_exception_does_not_break_completion``)
asserts that a crashing subscriber doesn't prevent the row from
landing in ``completed``.

### Default timeout = 900 s

Mirrors the v22.0.1 ``max_turns`` empirical guideline (≤ 80 turns ≈
≤ 15 min). Callers doing read-only Q&A should pass shorter
(``timeout_seconds=60``); refactor-scale tasks pass longer
(``timeout_seconds=1800``). Same shape as MCP HTTP request lifetime
budgets — most clients tolerate this.

## Lessons

### Universal vs ideal — ship universal first

The "right" v22.2.0 way is MCP resource subscription:
``resources/subscribe`` + ``notifications/resources/updated``.
Protocol-native, no held requests. But surfacing notifications to
the model side depends on the MCP client; some clients silently drop
them. ``await_*`` tools work on every MCP client because they're
just tool calls.

v22.2.0 will add the resource-subscription path as a PARALLEL channel
— the two are not mutually exclusive. Clients that support
subscriptions get push; clients that don't continue to use
``await_*``.

### No client-side support is the bar

The whole "agent A is idle between turns" constraint means even the
most beautiful push notification just disappears if the Claude Code
client doesn't auto-resume the session. ``await_*`` works because
the agent KNOWS it's waiting and is actively in a tool call — the
result lands as the tool result on the next turn, which is the
standard MCP flow.

## Carry-over to v22.2.0

- Implement ``resources/subscribe`` on the FastMCP side.
- Each job becomes resource URI ``harbormaster://jobs/<id>``.
- Register a subscriber on JobStore via ``add_subscriber`` that
  routes status changes to ``notifications/resources/updated``.
- Resource listing (``resources/list``) returns recent jobs filtered
  by status, project, inbox.
- ``resources/read`` returns the job's ``as_dict()`` JSON payload.
- Test the surface with a fake MCP client that captures notifications.

## Operator-facing note

After upgrading to v22.1.0:

- Every async-delegate caller can switch from "enqueue → loop
  polling" to "enqueue → await_delegated_task" in one swap.
- Fan-out callers should batch: ``delegate_task(...)*N → loop:
  await_inbox(inbox_id, since=<last>) → recall_pending_results``
  drains as work lands.
- ``recall_pending_results`` is still the only ``mark_read`` path.
  ``await_inbox`` is purely a wakeup; the caller is responsible for
  draining after.
- Default ``timeout_seconds=900`` is a soft cap; agents can re-call
  to extend.

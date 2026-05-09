# Design: streaming for `fan_out_ask`

**Status:** Open question, no implementation yet. Filed during the
v1.0.0a14 retro after the regular chunk-streaming work was widened
to `delegate_task` and `ask_project` (local + SSH). `fan_out_ask` is
intentionally **not** in `_STREAMING_TOOLS` because the right wire
shape isn't obvious yet.

## What `fan_out_ask` does today

`fan_out_ask(question, ...)` runs N parallel `ask_project` calls
across a project / host filter, then returns a single concatenated
markdown document with one section per target. The whole thing
takes `max_turns × claude_p_time × ⌈targets/max_concurrency⌉`
seconds — easily 2–5 minutes for a 20-project fan-out.

JSON mode users see 2–5 minutes of silence followed by one large
response. SSE chunk users (a14) see... the same thing today,
because `fan_out_ask` falls through to the heartbeat path.

## The question

When a single fan-out involves N parallel chunk streams, how do
we serialize them into one SSE response?

## Option A: server-side multiplexing with a `project` field

```
event: chunk
data: {"project": "alpha", "text": "Looking at the auth module..."}

event: chunk
data: {"project": "beta", "text": "The signal pipeline currently..."}

event: chunk
data: {"project": "alpha", "text": " — the rate limiter uses..."}

event: result
data: {<MCP envelope with the whole concatenated doc>}
```

- **Pro:** caller has one connection. Same as ask_project but
  with a discriminator.
- **Pro:** chunks are interleaved in real time — the user sees
  progress across the whole fleet, not "alpha is done, now beta
  starts producing."
- **Con:** the chunk shape is now non-uniform between
  ask_project (`{"text": ...}`) and fan_out_ask (`{"project":
  ..., "text": ...}`). Callers need a discriminator on the tool
  name.
- **Con:** server-side has to coordinate N async generators into
  one async iterator — moderate code.

## Option B: caller maintains N parallel SSE streams

The MCP wire stays simple — `fan_out_ask` just returns the
*plan* (list of projects) and the caller fires N separate
`ask_project` calls in parallel.

- **Pro:** zero new code on the daemon. Each per-project stream
  is identical to today's ask_project SSE path.
- **Pro:** chunk shape stays uniform across all tools.
- **Con:** the caller has to do the orchestration. FleetQ Bridge
  would need to grow a "open N sub-streams and forward them"
  notion, which is more complex than today's "open one stream
  and forward bytes."
- **Con:** loses one of `fan_out_ask`'s value props — the
  server-side concurrency limit. If the caller fires N
  unbounded, they hit Anthropic rate limits faster.

## Option C: hybrid — one stream, one final result

`fan_out_ask` SSE stays heartbeat-only (no chunks), but the final
`result` event is replaced with a `result` event per project as
that project finishes:

```
event: heartbeat
data: {"elapsed_ms": 5000}

event: project-result
data: {"project": "alpha", "result": {...}}

event: heartbeat
data: {"elapsed_ms": 12000}

event: project-result
data: {"project": "beta", "result": {...}}

event: result
data: {<MCP envelope with the whole concatenated doc>}
```

- **Pro:** simpler than A — no per-chunk multiplexing, just
  per-project terminals.
- **Pro:** preserves the "one stream, one terminal envelope"
  invariant by adding a new event type for partial completions.
- **Con:** still no incremental output *within* a single
  project — users see "alpha done after 60s" but not "alpha is
  10% done."
- **Con:** introduces an event type (`project-result`) that
  doesn't exist anywhere else in the wire.

## Recommendation (tentative)

**Option A** for v1.x and **defer** until first user feedback.
Reasons:

- A is the only option that gives true progressive UX inside a
  fan-out. B and C both have "wait for project X to finish, then
  start on its output" tail latency.
- The chunk-shape divergence is small — `{"text": ...}` vs
  `{"project": ..., "text": ...}` — and discriminating on the
  tool name is something callers already do (different tool, different
  semantics).
- If a future tool wants per-target multiplexing too, Option A's
  shape generalises (`fan_out_ask` becomes the first user; others
  follow with the same `project` discriminator under whatever
  that tool calls its targets).

The deferral is intentional: nobody has asked for `fan_out_ask`
streaming yet. Building the wrong shape and stabilising it is
worse than waiting for a real use case to clarify which option
actually matters.

## When to revisit

- A user asks for incremental fan-out output explicitly.
- We add more parallel-multi-target tools (e.g. a hypothetical
  `bulk_status`) and the second one would want streaming too.
- The streaming foundation needs a v1.x → v2 wire-shape revision
  for some other reason — at that point pick a unified
  multiplexing scheme.

## Out of scope for this design doc

- Backpressure (caller not draining fast enough): use the same
  approach as ask_project — sse-starlette will yield CPU between
  events; if the caller is slow, the server stalls naturally.
- Per-project errors interleaving with chunks: if Option A wins,
  add a `chunk-error` (or reuse `error` with a `project` field
  in `data`) that doesn't terminate the whole stream — fan-out
  semantics say one project's failure shouldn't kill the others.

# Sprint Retro — Harbormaster v2.1.0a4

**Date:** 2026-05-09
**Theme:** "Ask this project" lands on the project detail page. The
v1.0.0a14 SSE streaming dispatch finally has a browser-side surface
— users go from "view a project" to "stream a fresh answer from it"
without leaving the page. Headline feature of the v2.1 UI sprint.

## What landed

| SHA | Subject |
|-----|---------|
| (squash) | feat(ui): "Ask this project" SSE form (#26) |

## Capabilities

### 1 · `_partials/ask_form.html`

New Jinja partial — Alpine component that renders a textarea +
max_turns input + submit/stop buttons + result pane. Receives the
project name and host from the parent template via `{{ value | tojson }}`.

### 2 · Browser-side SSE consumer (without EventSource)

EventSource is GET-only and can't carry an MCP request body. Instead:

```js
const r = await fetch('/mcp/harbormaster', {
  method: 'POST',
  signal: controller.signal,
  headers: { 'Content-Type': 'application/json',
             'Accept': 'text/event-stream' },
  body: JSON.stringify({ method, params }),
});
const reader = r.body.getReader();
// → manual SSE block parsing (split on "\n\n", parse "event:" + "data:")
```

Three event types handled:
- `chunk`     → append `delta`/`chunk` to the live pane
- `result`    → fall-through render when no chunks arrived
                (non-streaming tool path; e.g. project_status)
- `error`     → red error band
- `heartbeat` → no-op (keeps connection alive across reverse proxies)

### 3 · UX details

- min 3 chars submit gate
- max_turns numeric (1-10, default 5)
- live "streaming…" indicator
- final "N chunks · X.Xs" stats row when complete
- AbortController-wired "stop" button while in-flight
- Result pre-block uses `whitespace-pre-wrap break-words` so long
  lines wrap on mobile

## Real numbers

- 1 PR opened / merged (#26)
- 3 new tests
- Test suite: 542 → **545 pass, 1 skip**
- mypy --strict: 46 source files clean
- ruff: clean
- Backwards-incompatible changes: 0
- Lines changed: +201 / -3

## What worked

- **fetch streaming over EventSource.** The native streaming Response
  API is well-supported and lets us POST + receive SSE in one call.
  ~30 lines of consumer code; AbortController bonus = clean cancel.

- **Jinja `tojson` for safely embedding context.** Project name and
  host get JSON-encoded into the Alpine x-data initializer. No XSS
  surface even if a project name has weird chars.

- **Partial reuse intent.** Shipping the form as
  `_partials/ask_form.html` sets up reuse on the dashboard cards
  (P1 #6 from the research) without forcing the dashboard rewrite
  in this phase. v2.1.0a5 / a6 can lift it onto the dashboard if
  desired.

## What to change / next

- **Token-based UI auth not plumbed.** Loopback no-auth (the common
  setup) works as-is. Bearer-protected installs need the token
  added to fetch headers. Defer to v3 / Custom Connector story.
- **No question history in the form.** Every submit clears the
  prior result. Prior questions are visible via recall search if
  history is enabled, but a small "previous question" recall in
  the form itself would be nicer.
- **No copy-result button.** Users will want to copy the streamed
  answer. Trivial follow-on.

## Action items for the next sprint (v2.1.0a5)

1. **fan_out_ask + delegate_task forms.** Two new pages or one
   shared `/tools` index. Multi-select project chips for fan_out;
   structured deliverable input for delegate. Reuse the
   `_partials/ask_form.html` SSE consumer pattern.

## Out-of-scope (still)

- Tauri / Electron desktop UI wrapper
- Token plumbing for bearer-protected installs
- Question history in the form
- Headless browser tests

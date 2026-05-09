# Sprint Retro — Harbormaster v1.0.0a15

**Date:** 2026-05-09
**Theme:** v1.0 surface feature-complete. The A2A Agent Card per
project lands, three docs deliverables close out the v1.0.0a14
backlog, and the README roadmap re-baselines against reality.
What's left between here and `v1.0.0` GA is the v1.2 phase
(Q&A history, federated KG, auto project graph) plus an
operator guide.

## What landed

### `harbormaster` (this repo)

| SHA | Subject |
|-----|---------|
| `b199081` | feat(ui): A2A Agent Card per project + a15 docs bundle (#9) |

## Capabilities (this sprint)

### 1 · `GET /agent-card/<project-name>`

Each `~/htdocs/<project>` returns an A2A v0.3 agent card. Convention:
the MCP "project" axis maps to the A2A "agent" axis. Three skills
per card:

- `ask-<project>` — Ask. Streams via SSE, returns markdown summary.
- `delegate-<project>` — Delegate read-only task. v1 fail-closed.
- `status-<project>` — Project status. JSON only.

Capabilities advertised: `streaming: true`, `stateTransitionHistory:
false`, `pushNotifications: false`. `defaultInputModes: ["text/plain"]`,
`defaultOutputModes: ["text/event-stream", "application/json"]`. A
vendor-namespaced `metadata.harbormaster` block carries
`version`, `project_path`, `has_serena`, `has_claude_md` for
consumers that want richer context loading.

`url` is the absolute MCP invocation URL — built from the request
Host header so it's correct behind a reverse proxy. Same bearer
middleware as the rest of the UI.

### 2 · `docs/design-fan-out-streaming.md`

1-page design exploring three options for `fan_out_ask` chunk
streaming: server-side multiplexing (Option A), caller-side N
streams (B), per-project terminal events (C). Tentative
recommendation: A. Implementation deferred until first user
feedback. Explicit revisit triggers listed.

### 3 · `docs/architecture-harbormaster.md` §16

New "Reverse-proxy / nginx configuration for streaming" section.
nginx `proxy_buffering off` + 300s read/send timeouts recipe.
What the daemon does on its end (PHP-FPM `ob_get_clean()` loop;
FastAPI no-op). Verification curl + debugging hint for
"chunks all arrive at the end" symptom.

### 4 · README roadmap rebaseline

Old "weeks 1-2 / 3-4 / 5-6" projection retired. New shape:

| v1.0 | **Complete (a8–a14)** | (long list of deliverables) |
| v1.1 | **In progress (a13–)** | Per-deliverable check-marks linked to sprints |
| v1.2 | Pending | Q&A history, federated KG, auto project graph |

## Real numbers

- 4/4 a14 retro action items shipped (items 1, 2, 3, 4)
- 1 PR opened, merged
- 6 new test_ui cases for `agent_card`
- Test suite delta: 242 → 248 passed on harbormaster (1 skipped)
- Pint clean, ruff + mypy --strict clean across 26 source files
- 0 backward-incompatible changes

## What worked

- **Bundling the docs items into one PR with the A2A endpoint.**
  All four were tightly related (A2A unblocks v1.1; the docs
  rebase the roadmap that A2A closes; the nginx doc is what
  operators need to deploy A2A behind a proxy correctly).
  Splitting them would have meant 4 PRs with duplicated context.
- **The design doc convention — explicit revisit triggers.**
  `docs/design-fan-out-streaming.md` lists "user asks for it",
  "second multi-target tool wants streaming", "wire-shape revision
  for some other reason." Means the deferral is conditional, not
  forever, and future-me has clear exit criteria.
- **Vendor-namespaced metadata in the A2A card.** A2A consumers
  that don't care ignore it; consumers that do (e.g. an A2A-aware
  Claude Code that wants to auto-load the project's CLAUDE.md)
  get exactly the structured fields they need without parsing
  description text. Better than "stuff it in description" or
  "extend the schema."
- **Roadmap rebaseline as docs.** Most projects let the roadmap
  table go stale and silently no longer match reality. Putting
  per-deliverable check-marks linked to sprint numbers makes the
  roadmap part of the audit trail, not aspiration.

## What to change / next

- **`metadata.harbormaster.project_path` leaks an absolute path.**
  In single-tenant local use that's fine; once we have multi-user
  hosting it'd disclose home directory layouts. Consider a
  policy: include only when the request comes from localhost / a
  bearer-authenticated session, redact otherwise. Not blocking
  v1.x but worth noting.
- **A2A schemaVersion is pinned to "0.3.0" as a string.** If A2A
  ships v0.3.1 with additive fields, we won't reflect them and
  consumers might reject. Worth a "compatibility test" pattern —
  load the upstream A2A schema spec and assert our shape is a
  valid subset. Defer until A2A ships a v0.4 and we know what
  changed.
- **The `metadata.harbormaster.version` field would benefit from a
  schema-stability marker.** `version: "1.0.0a15"` says nothing
  about whether the metadata block's *shape* is stable. Future:
  add `metadata.harbormaster.metadata_schema_version` so
  consumers can pin against the metadata block's API
  separately from the daemon version.
- **The cumulative session has now shipped 9 sprints (a8 publish
  recovery + a10–a15) in one window.** Running test count:
  212 → 248. Production-merged PRs: ~12 across two repos. The
  velocity is unsustainable in any normal collaboration mode.
  Recommendation: any v1.2 work should start in a fresh session
  for clearer thinking on Q&A-history schema design and federated
  KG semantics.

## Action items for the next sprint (v1.0.0a16 / week 16)

1. **Q&A history with semantic dedup (v1.2 phase 1).** sqlite-vec
   per-host trajectory store. Schema: `(question_embedding,
   answer, project_name, host, created_at, claude_p_cost_cents)`.
   New tools: `recall_qa(question, top_k)`. Retention policy:
   keep N most recent + most-recalled.
2. **Memory writeback to FleetQ Memory domain (v1.1 last item).**
   When `[fleetq]` is enabled, after every successful
   `ask_project` / `delegate_task` call, POST the trajectory to
   `/api/v1/memory` (existing FleetQ endpoint). Opt-in.
3. **Operator guide.** `docs/operator-guide.md` covering: deploy
   (uvx / pipx / docker), configure (TOML reference), harden
   (auth, network), monitor (logs, smoke jobs), upgrade (PyPI tag
   pull). Closes the "deployment story" gap before v1.0.0 GA.

## Out-of-scope (still)

- Backends other than Claude — wait for first user request.
- Plugin / extensions API — v2.
- Tauri / Electron native UI wrapper — post-v1.2.
- Relay-binary path (Path B) — explicitly skipped in favour of Path C.
- Per-token streaming through the relay-mode bridge — relay
  frames are Redis chunks, not SSE.
- `fan_out_ask` chunk streaming — design doc filed; await user
  feedback.
- Federated KG via FleetQ KnowledgeGraph domain — v1.2 phase 2,
  needs Q&A history schema landed first.
- Auto project graph — v1.2 phase 3, parsers for composer.json /
  package.json / pyproject.toml.
- Cross-session memory recall — v1.2 phase 4, builds on KG.

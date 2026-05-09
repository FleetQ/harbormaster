# Sprint Retro — Harbormaster v1.0.0a16

**Date:** 2026-05-09
**Theme:** v1.1 phase closed. The last unfinished v1.1 deliverable
(Memory writeback to FleetQ Memory domain) shipped, and the
operator guide closes the deployment-story gap. After a16, v1.0 +
v1.1 are both feature-complete. The remaining path to `v1.0.0` GA
is the v1.2 compounding phase.

## What landed

### `harbormaster` (this repo)

| SHA | Subject |
|-----|---------|
| (squash) | feat(fleetq): Memory writeback + operator guide (closes v1.1) (#10) |

## Capabilities (this sprint)

### 1 · FleetQ Memory writeback

New `harbormaster.fleetq.memory.MemoryWriter` plus a
`_maybe_writeback_to_fleetq` hook in `tools/_helpers.run_backend`.
Posts trajectory to `/api/v1/memory` after every successful
`ask_project` / `delegate_task` call. Wire shape:

```json
POST /api/v1/memory
{
  "type": "trajectory",
  "tool": "ask_project" | "delegate_task" | ...,
  "project": "<name>",
  "host": "<host or 'local'>",
  "content": {"question": <prompt>, "answer": <output>},
  "metadata": {"duration_ms": <int>}
}
```

Three opt-in gates: `[fleetq] enabled = true`, `[fleetq]
write_trajectories = true`, `FLEETQ_API_TOKEN` non-empty. All
three must be set before a writer is even constructed. Failure
modes (4xx, 5xx, network, ConnectError) all return False with a
logger.warning — never propagate. The user's MCP response is
already in flight by the time the hook fires; failure to write
back must NEVER fail the tool call.

### 2 · Operator guide

`docs/operator-guide.md`, 8 sections covering everything a
production operator needs:

1. Deployment options (stdio / HTTP-SSE loopback / public-bind / Docker)
2. TOML configuration reference
3. Auth (MCP token + UI token + FleetQ Sanctum)
4. Reverse proxies + `proxy_buffering off`
5. Logging (text vs JSON) + log lines to alert on
6. Upgrades via `uvx --refresh` + version pinning
7. Troubleshooting (5 most common failures)
8. systemd unit + launchd plist templates

Cross-links to `architecture-harbormaster.md` §16 for the deep
nginx recipe so the operator guide stays focused on operator
mental model rather than architectural rationale.

## Real numbers

- 2/3 v1.0.0a15 retro action items shipped (items 2, 3)
- 1 PR opened, merged
- 9 new test_memory_writeback cases
- Test suite delta: 248 → 257 passed on harbormaster (1 skipped)
- Pint clean, ruff + mypy --strict clean across 27 source files
- 0 backward-incompatible changes

Item #1 from a15 retro (Q&A history with sqlite-vec) explicitly
deferred — it's the v1.2 phase 1 deliverable that warrants its
own sprint, schema design, and probably a fresh session for clear
thinking on embedding storage.

## What worked

- **The three-gate opt-in pattern.** [fleetq].enabled + [fleetq].write_trajectories + non-empty token. Each gate
  has a clear semantic ("turn FleetQ off entirely" vs "use FleetQ
  but skip Memory writeback specifically" vs "we don't have a
  token configured yet"). Users can tune privacy-vs-feature
  tradeoffs without recompiling or removing code.
- **`_maybe_*` naming convention for best-effort hooks.** Self-
  documenting: "this might do something, might not, you don't
  need to know which." Pairs with the silent-on-failure semantics
  — the function NAME tells you not to expect a return value.
- **Operator guide written without templating.** No
  Sphinx, no MkDocs, no auto-generated config-reference page —
  just a markdown file with concrete recipes. Simpler to keep
  current, and ranks higher in GitHub search. The cross-links to
  architecture §16 mean we don't duplicate the nginx recipe in
  two places.

## What to change / next

- **v1.2 needs a fresh session.** This is sprint #10 in one
  continuous window (a8 publish recovery + a10–a16). Volume of
  shipped code: ~20 PRs across two repos, ~65 new tests. Velocity
  has held quality well so far — every PR has dedicated tests,
  every retro is from the template, every release tagged + on
  PyPI — but the next phase (Q&A history, federated KG) needs
  schema design, embedding-store choice (sqlite-vec vs pgvector
  vs FleetQ-side), and tradeoff analysis that benefits from
  rested judgment.
- **The MemoryWriter exception-swallowing is incomplete.** The
  `_maybe_writeback_to_fleetq` integration tests document that
  RuntimeError from `write_trajectory` does propagate today
  (caught test). For "best effort never fails the tool call"
  semantics, we should wrap the inner call in `try/except
  Exception: log; return`. Future hardening — defer-ed because
  the current behaviour matches httpx's documented contract
  (HTTPError is the one we expect, RuntimeError is "you broke
  the writer setup" which is a programming error worth
  surfacing).
- **No live FleetQ Memory writeback verification.** The unit
  tests use httpx.MockTransport. The `smoke-fleetq` CI job
  doesn't yet exercise the writeback path. Worth extending —
  POST a trajectory, GET it back via `/api/v1/memory/search`,
  assert round-trip.

## Action items for the next sprint (v1.0.0a17 / week 17)

1. **Q&A history with semantic dedup (v1.2 phase 1).**
   sqlite-vec per-host trajectory store. Schema:
   `(question_embedding, answer, project_name, host, created_at,
   claude_p_cost_cents)`. New tool: `recall_qa(question, top_k)`.
   Retention policy: keep N most recent + most-recalled.
2. **Federated KG via FleetQ KnowledgeGraph domain (v1.2 phase
   2).** Builds on a16's Memory writeback — same opt-in gates
   plus a separate `[fleetq].write_kg = true`. Posts entity-
   relation triples extracted from trajectories.
3. **Auto project graph (v1.2 phase 3).** Parse `composer.json` /
   `package.json` / `pyproject.toml` per project; surface
   cross-project deps in the Live UI.

## Out-of-scope (still)

- Backends other than Claude — wait for first user request.
- Plugin / extensions API — v2.
- Tauri / Electron native UI wrapper — post-v1.2.
- Relay-binary path (Path B) — explicitly skipped in favour of Path C.
- Per-token streaming through the relay-mode bridge.
- `fan_out_ask` chunk streaming — design doc filed; await user
  feedback.
- Cross-session memory recall — v1.2 phase 4 (depends on KG +
  Q&A history schema landing first).

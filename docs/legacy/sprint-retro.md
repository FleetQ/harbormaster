# Sprint Retro — Project Router MCP v1

**Date:** 2026-05-08
**Phase:** Think → Plan → Build → Review → Test → Ship → Reflect (full sprint)
**Outcome:** Shipped to Jarvis user-scope MCP. ✓ Connected. 9/9 tests pass.

## What landed

- `~/htdocs/project-router-mcp/` — single-file Python MCP server (`src/server.py`, 230 lines incl. comments).
- 4 tools: `list_projects`, `project_status`, `ask_project`, `delegate_task`.
- 9 tests (5 smoke + 4 integration) — all passing.
- Registered as `project-router` in `~/.claude.json` (user scope) via `claude mcp add`.
- Live verification: `claude mcp list` → `✓ Connected`.

## Real numbers

| Metric | Result |
|---|---|
| `list_projects` over 52 real projects | ~857ms |
| `project_status(agent-fleet)` | 169ms |
| Lines of code (server.py) | ~210 |
| Tests written | 9 |
| Sprint duration | ~1 chat turn |

## What worked

- **Single-file `uv run` script with PEP 723 inline deps.** Zero install, no venv setup. Just `claude mcp add ... uv run server.py`.
- **Auto-discovery via filesystem** (no config). Drop a project into `~/htdocs/` and it appears.
- **Fail-closed `delegate_task`** — refuses writes in v1. No accidental destruction; explicit gate for v2.
- **Path traversal guard** (`HTDOCS.resolve() in p.parents`) — closed during Review, no test pivot needed.
- **Subprocess timeout + word cap** — main session can't be flooded by a misbehaving subagent.

## Surprises

- `accounting-fleetq` is not at `~/htdocs/accounting-fleetq/` — it lives elsewhere (probably `crm-fleetq`). The router returned a clean error with available projects, validating the error path serendipitously. Memory note: confirm project paths before assuming.
- 52 projects in `~/htdocs/`. Larger blast radius than expected. `list_projects` may need pagination/caching in v2 if it grows past 100.

## Decision gate: Опция 3 (Letta Code self-host)?

**Recommendation: PAUSE. Validate router for 3–7 days first.**

Why pause:
1. Router shipped 3 minutes ago. Zero real-world usage data.
2. Letta self-host = 2–5 days. Don't sink that cost until router's gaps are concrete.
3. The "wow" features Letta adds over router (continual learning, multi-month memory, autonomous loops) only matter if router's session-bound model proves insufficient.

**Validate router with these checks before proceeding to Letta:**

- [ ] After 3 days: have I avoided ≥10 cwd switches by using `project-router__ask_project`?
- [ ] After 1 week: are there questions I asked the router that it answered well but I had to re-ask later because it forgot? *(If yes → Letta's persistence helps. If no → Letta is overkill.)*
- [ ] Has `delegate_task` failing-closed blocked any real work? *(If yes → either lift the gate in v1.1, or graduate to Letta which has a real approval system.)*

If 2+ checks fail in user's favor (router suffices), **STOP** — keep router, skip Letta.

If 2+ checks fail against router, restart sprint with Letta scope.

## Action items

- [x] Restart Claude Code session to pick up new MCP server (user action)
- [x] Use `project-router__project_status` next time you want a quick "what's up with X" cross-project
- [ ] After 3 days: re-evaluate Letta gate above
- [ ] If router list_projects exceeds 1.5s (currently 857ms over 52 projects), add 30s in-process cache

## What to keep doing

- Single-file scripts with PEP 723 inline deps for tools at this scope. The dep boilerplate-to-value ratio is unbeatable.
- Fail-closed defaults on write operations — review-time decision that paid off in code clarity.
- Real integration tests (skipped by default, opt-in via env) over heavy mocking. The ROUTER_RUN_LIVE pattern works.

## What to stop / change

- Don't auto-cache list_projects yet — premature.
- Don't add streaming until a real task needs it.
- Don't expand to Friday/SSE until usage demands distributed access.

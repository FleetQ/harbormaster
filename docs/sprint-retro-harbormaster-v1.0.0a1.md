# Sprint Retro — Harbormaster v1.0.0a1

**Date**: 2026-05-08
**Mode**: `/sprint-orchestrate full`
**Goal**: Plan + implement `project-runner` v1, give it a unique FleetQ-adjacent name
**Outcome**: ✅ Shipped v1.0.0a1 scaffolding + security hardening on `feat/harbormaster-v1.0`. Tagged.

---

## Phase timeline

| Phase | Output | Notes |
|-------|--------|-------|
| Think | `docs/design-harbormaster.md` | 4 forcing questions answered in one batch |
| Plan | `docs/architecture-harbormaster.md`, `docs/test-plan-harbormaster.md` | 6-week phased v1.0 → 1.2 |
| Build | `581bb62` (29 files, +3040/-761) | Single-file v0.1 → 15-file package |
| Review | kieran-python agent (background) | 2 show-stoppers + 6 important + 4 nice-to-have |
| Test | ruff + mypy + pytest | 23/24 → 59/60 after security tests |
| Ship | Tag `v1.0.0a1` (local) | Remote push pending user authorization |
| Reflect | this doc | — |

---

## What landed

**Naming + repo**

- Name **Harbormaster** chosen over Quay / Bosun / Cue (naval role match, low brand collision, pairs naturally with FleetQ).
- `~/htdocs/project-router-mcp` renamed in-place to `~/htdocs/harbormaster`.
- Branch `feat/harbormaster-v1.0` off `feature/v1-router`.
- Tagged `v0.1.1` (last v0.1-line state with SSH support) and `v1.0.0a1` (first Harbormaster tag).
- Target GitHub org: `github.com/FleetQ/harbormaster` (not yet created).
- License: **MIT**.

**Build deliverable (v1.0 week 1 milestone)**

- Single-file `src/server.py` → proper Python package:
  ```
  src/harbormaster/
    __init__.py, __main__.py, server.py, config.py,
    projects.py, ssh.py,
    backends/{__init__, base, claude}.py
    tools/{__init__, _helpers, projects, ask, delegate, hosts}.py
  ```
- `pyproject.toml`: hatchling build, `harbormaster-mcp` on PyPI, optional `[ui]`/`[fleetq]`/`[dev]` extras, `harbormaster-mcp` console_scripts entry.
- TOML config layer (pydantic v2) with per-project `./.harbormaster.toml` override.
- Backend `Protocol` abstraction; default `ClaudeBackend`. Codex/Aider/Gemini follow same contract in v1.0.x patches.
- README rewritten for Harbormaster; v0.1 docs preserved under `docs/legacy/`.

**Security hardening (in response to review)**

- `validate_project_name(name)` — single trust gate, strict regex `^[A-Za-z0-9][A-Za-z0-9._-]*$`. Called by `resolve_project` (local) AND by both remote dispatch paths (`tools/_helpers.run_backend` and `tools/projects._remote_status`) — both were vulnerable to `name='..'` traversal via `cd`.
- `discover_projects` symlink-out-of-base containment guard — closes traversal-via-discovery.
- Pydantic config tightened: `log_level: Literal[...]`, `Field(gt=0)` on every timeout/port/word_cap, `model_config = ConfigDict(extra='forbid')` so TOML typos fail at load.
- Dump-dir moved from world-readable `/tmp` to `$XDG_STATE_HOME/harbormaster/dumps` with mode 0700/0600.
- SSH error hints: when `BatchMode=yes` blocks an interactive prompt (host-key, password), the error string now points the user at the specific fix.

---

## Real numbers

| Metric | v0.1 | v1.0.0a1 |
|--------|------|----------|
| Source files | 1 (`server.py`) | 15 |
| Source LOC | 511 | ~860 |
| Tests | 9 | 60 (59 pass, 1 skip) |
| Lint | manual | `ruff` clean |
| Types | untyped | `mypy --strict` clean |
| Packaging | PEP 723 inline deps | hatchling / PyPI-ready |
| Transports | stdio | stdio (HTTP/SSE → v1.0.0a2) |
| Backends | hard-coded | Protocol + 1 implementation |

---

## What worked

- **Pre-Plan asking 4 forcing questions in one batch via `AskUserQuestion`.** Fast convergence on name (Harbormaster), audience (3 layered tiers), v1 scope (full), compounding (FleetQ KG). User got progress without a long Q&A loop.
- **kieran-python reviewer running in background.** Found two real show-stoppers I had missed (`resolve_project` traversal + remote `cd` injection via unquoted name). Both were security-relevant. Reviewer ran while I did `ruff` / `mypy` in foreground — zero idle time.
- **Atomic restructure commit (`581bb62`).** Moving 29 files in one commit kept the v0.1→v1.0 boundary clean. Diff is reviewable as a single unit; rollback is trivial.
- **Architecture doc as forcing function.** Week-by-week phasing in §15 turned out useful when scope pressure showed up: I could honestly mark "week 1 done; weeks 2–6 in subsequent sprints" without losing user trust or shipping vapor.
- **Pydantic v2 + `extra='forbid'`.** Cost: a few keystrokes per section. Benefit: typos in TOML fail loudly at startup instead of silently being ignored.

---

## Surprises

- **FleetQ is much bigger than I assumed.** Pointed at `~/htdocs/agent-fleet/`, expected a queue, found a 39-domain Laravel mission-control platform with 579 MCP tool files. Re-positioned Harbormaster from "OSS MCP server" to **"OSS adapter for the FleetQ ecosystem"** — a meaningfully stronger launch story.
- **Reviewer caught what I had rationalized.** I had told myself "discover_projects only returns from the glob walk, so it's inherently safe." That missed the symlink case AND the remote-`cd` case. Would have shipped a vulnerable v1 without the review.
- **Hand-rolled glob splitter is fragile.** I knew it; reviewer confirmed; deferred to v1.0 polish. Important to keep "works for the happy path" vs "robust" explicit and visible.

---

## Decisions worth recording

- **Name: Harbormaster** — naval role match, pairs naturally with FleetQ, low brand-collision risk.
- **`github.com/FleetQ/harbormaster`** — not personal `escapeboy/`. Sets up FleetQ-org pattern for future OSS spin-offs (sister projects can land in same org).
- **MIT license** — adoption priority over patent-grant defensiveness. Can be re-licensed up to Apache 2.0 later if enterprise customers ask.
- **6-week comfortable budget** over 3-week aggressive. Shippable milestone every 2 weeks (v1.0 → 1.1 → 1.2).
- **Pluggable backend Protocol from day one** — even though v1.0 only ships `ClaudeBackend`. Costs ~30 LOC; pays back the moment a contributor adds Codex / Aider / Gemini.

---

## What to keep doing

- Atomic restructure commits with detailed messages that explicitly call out **out-of-scope**.
- Pydantic v2 with `extra='forbid'` and `Field` constraints. The strictness cost is paid once; the typo-catching benefit accrues forever.
- `TypeGuard` on predicate functions (`is_remote`) — narrows mypy without `assert` ceremonies at every call site.
- Run review agent in background while doing other QA work foreground.
- Phase architecture doc by week so scope pressure has a defined release valve.

---

## What to change / next

- **Don't drop security guards in a refactor without an explicit replacement.** v0.1 had an `HTDOCS in p.parents` containment check; v1.0a1 implicitly dropped it. Reviewer caught the regression. Mental checklist update: when removing a check, document why or replace it.
- **Test-count target should be a forcing function from Build, not a Review remediation.** Test plan said ≥60 unit tests for v1.0; first commit shipped at 21. Without security review pushing me to 60, I would not have hit the target. Treat the test count as a Build acceptance criterion next sprint.
- **The biggest remaining gap is real subprocess testing.** Current tests stub `subprocess.run`; the live `claude -p` test is gated behind `HARBORMASTER_RUN_LIVE=1` and skipped by default. Need at least one CI-runnable e2e using a fake `claude` shim binary.

---

## Action items for the next sprint (v1.0.0a2 / week 2)

1. HTTP/SSE MCP transport alongside stdio.
2. `fan_out_ask` MCP tool with concurrency cap.
3. Live UI scaffold (project grid + SSE feed).
4. Replace hand-rolled glob splitter with `pathlib.Path.glob(recursive=True)` and `fnmatchcase` excludes (review #7).
5. Tighten `Backend` Protocol — `BackendResult` end-to-end, `parse_remote_stdout` made private (review #4).
6. Cheap `find_project_path(name, cfg)` helper that avoids N `git` spawns per `ask_project` call (review #8).
7. `.github/workflows/ci.yml` — ruff + mypy + pytest matrix on Ubuntu+macOS, 3.11/3.12/3.13.
8. **User-authorization-required**: create `github.com/FleetQ/harbormaster`, push `feat/harbormaster-v1.0`, open draft PR, tag the v1.0.0a1 release.

---

## What did not happen in this sprint (and why)

- **GitHub repo + push + PR**: requires user authorization for actions that affect external state. The local repo is tagged and ready; awaiting explicit approval before `gh repo create` / `git push`.
- **HTTP/SSE transport, `fan_out_ask`, Live UI**: by architecture-doc design these are week-2 work. Held the line on scope.
- **FleetQ Bridge / Platform Tool integration**: weeks 3–4 per architecture. Untouched as planned.
- **Three "important" review findings (#4, #7, #8)**: all are larger refactors that would have made this sprint a 4-commit affair instead of 2. Documented in the security commit footer; queued for v1.0.0a2.

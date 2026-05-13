# Contributing to Harbormaster

Thanks for considering a contribution. This file documents the
shipping conventions that have evolved across 40+ PyPI releases —
following them keeps PRs unsurprising and reviewable.

> **Read first**: [`docs/architecture-harbormaster.md`](docs/architecture-harbormaster.md)
> for the system shape and [`docs/operator-guide.md`](docs/operator-guide.md)
> for the runtime view. Per-version retros under
> `docs/sprint-retro-harbormaster-v*.md` are the canonical record of
> *why* things look the way they do.

## Quick start (development)

```bash
# Clone + install with all extras for local dev
git clone https://github.com/FleetQ/harbormaster.git
cd harbormaster
uv sync --extra ui --extra fleetq --extra history --extra dev

# Run the full test suite (target: passes in < 2 min)
.venv/bin/pytest tests/ -q

# Type-check (must stay clean — CI gates on this)
.venv/bin/mypy --strict src/harbormaster

# Lint (must stay clean — CI gates on this)
.venv/bin/ruff check src/ tests/
```

## Ship rhythm (alpha-by-alpha)

Releases follow a strict pattern proven across the v3, v4, v5, v6,
v21, and v22 GA lines:

```
feat branch  →  CI green (8 jobs)  →  squash/FF-merge to main
            →  bump __version__ + write sprint retro  →  git tag vX.Y.Za<N>
            →  PyPI Trusted Publishing auto-fires via publish.yml + verify-ci gate
```

### Feature branch naming

```
feat/v<line>-<short-topic>     e.g. feat/v22.1-await-tools
fix/v<line>-<short-topic>      e.g. fix/v21.0.1-timing-attack
```

One topic per branch. Once shipped, the branch can be deleted —
the squash commit on `main` is the canonical record.

### Commit message format

```
ship: v<X.Y.Z><alpha?> — <imperative one-line summary>

<body — what changed, why, how it was tested, lessons captured>

Co-Authored-By: <co-author lines if applicable>
```

`ship:` prefix marks a publishable version bump. `feat:`, `fix:`,
`docs:`, `ci:`, `test:`, `refactor:` for non-shipping commits on
feature branches.

### Version bumps

`src/harbormaster/__init__.py` carries `__version__`. Bump it in the
same commit as the sprint retro. Alphas: `22.0.0a5`. GA: drop alpha.
Patches: `22.0.1`. Minors (new feature, backward-compatible):
`22.1.0`.

### Sprint retro requirement

**Every shipped version writes a retro at
`docs/sprint-retro-harbormaster-v<X.Y.Z>.md`** using
`docs/sprint-retro-TEMPLATE.md` as the section structure. The retro:

- Captures what shipped and why
- Lists every lesson learned (especially failures and near-misses)
- Forward-references the next sprint's a1 candidate
- Notes operator-facing upgrade caveats

This discipline carried the project through v22.0.1 (production
incident → diagnosed and patched in <90 minutes) — the retro is what
makes future debugging fast.

## Quality gates (all enforced in CI)

| Gate | Tool | Failure means |
|---|---|---|
| Tests pass | `pytest tests/` × 6 OS/Python combos | No merge |
| Type-check clean | `mypy --strict src/harbormaster` | No merge |
| Lint clean | `ruff check src/ tests/` | No merge |
| HTTP smoke | curl + spawn full stack | No merge |
| UI smoke (no-auth) | requests against /api/health | No merge |
| UI smoke (with-token) | bearer-token roundtrip | No merge |
| MCP streaming smoke | SSE chunks flow end-to-end | No merge |
| Build wheel + sdist | hatchling | No PyPI publish |

The `publish.yml` workflow has a `verify-ci` job that polls for the
CI workflow's conclusion on the tagged SHA. PyPI Trusted Publishing
only fires once verify-ci sees `conclusion=success`. **No untested
build ever reaches PyPI.**

## Code conventions

### Python style

- Python 3.11+, `from __future__ import annotations` at the top of
  every `.py`
- All public functions typed; private helpers prefix `_`
- Pydantic models for wire shapes (config, MCP tool inputs, FleetQ
  payloads)
- No global mutable state — pass `HarbormasterConfig` explicitly
- `pathlib.Path` over `os.path`; `contextlib.suppress` over
  bare-except-pass; `match` over big if-ladder when the dispatch is
  enum-shaped

### Tests

- `pytest` with `pytest-asyncio` for async; `pytest-httpserver` for
  HTTP mocks
- One source file → one test file, mirror the path
  (`src/harbormaster/foo/bar.py` → `tests/foo/test_bar.py`)
- New behaviour landing without tests is not a valid PR
- Coverage gate: net LOC ratio test-vs-source ≥ 25% across the sprint
- For SSE / long-running generators, **test at source level**
  (route registration, subscriber wiring, broadcaster invocation) —
  `TestClient` does not cleanly consume infinite
  `EventSourceResponse` and will hang. Real SSE behaviour is verified
  manually against the running daemon. See
  `tests/integration/test_jobs_sse_stream.py` for the pattern.

### Naming patterns

- `_maybe_*` — best-effort hooks that may no-op silently
- `*_stream` — generator / iterator variants of sync functions
- `_apply_migrations` — idempotent ADD COLUMN runner on store init

### Opt-in gates (three-gate pattern from a16)

For any feature that writes outside the harbormaster process
boundary (FleetQ, KG, history, jobs):

```
1. Feature toggle      [domain] enabled = true       (default false)
2. Sub-feature toggle  [domain] write_<thing> = true (allows partial)
3. Credential check    env var or token must be set
```

All three must pass before the writer is constructed. Failures
inside the writer always swallow + `logger.warning` — never propagate
to the user-facing tool call.

### Idempotent schema migrations (v21.0.8 + v22.0.1 pattern)

For SQLite-backed stores: PRAGMA table_info to enumerate existing
columns; ALTER TABLE ADD COLUMN only the missing ones. Carry a
`MIGRATIONS: list[tuple[str, str]]` list in the schema module. Run
in store `__init__`. Schema-only migrations supported; data
backfills go in explicit one-shot helpers.

## Dependencies discipline

Core deps lean: only `mcp` + `pydantic`. Everything else gated
behind extras: `[ui]`, `[fleetq]`, `[history]`, `[dev]`. New extras
require explicit user opt-in
(`uvx --extra ui --extra fleetq harbormaster-mcp`).

Prefer stdlib over new deps where reasonable. Adding a dependency
needs a sprint-retro justification.

## Release process (operator end)

```bash
# 1. Implement on feat/<short-name> branch
git checkout -b feat/v22.1-await-tools
# ... commits ...

# 2. Open PR or push branch — CI must pass all 8 jobs

# 3. Fast-forward merge to main (squash if many small fixups)
git checkout main
git merge feat/v22.1-await-tools --ff-only

# 4. Bump __version__ + write sprint retro
# ... edit src/harbormaster/__init__.py + docs/sprint-retro-*.md ...
git commit -m "ship: v22.1.0 — <subject>"

# 5. Push main, then tag + push tag
git push origin main
git tag v22.1.0
git push origin v22.1.0

# 6. PyPI Trusted Publishing fires automatically.
#    Verify on https://pypi.org/project/harbormaster-mcp/
#    (PyPI metadata cache lag: ~5-15 min before `uv tool upgrade`
#     sees the new version; force-refresh via
#     `uv tool install --reinstall --refresh ...` if needed)
```

## Post-deploy verification (mandatory)

When deploying to the operator's own machine
(launchd-supervised daemons on macOS), run the 5-step check captured
in `daemon-supervision-runbook` memory:

1. `curl -s http://127.0.0.1:7531/api/health` — confirm new version
2. `launchctl list | grep harbormaster` — confirm NEW PIDs after
   `launchctl kickstart -k gui/$(id -u)/com.harbormaster.{ui,mcp}`
3. `curl -s http://127.0.0.1:7531/api/delegated-jobs/summary` —
   triggers JobStore subsystem init + applies any pending schema
   migrations
4. `tail -10 ~/.harbormaster/logs/{ui,mcp}.err` — no new errors
5. Functional probe of the new feature surface (the retro lists what
   to probe)

A deploy isn't done until all 5 pass.

## Where to ask questions

- File an issue on GitHub for bugs / feature ideas
- Open a discussion for "should we do X" questions
- For organisational context (decisions, prior discussions, FleetQ
  team Slack threads), check the operator running this fork — the
  alpha-by-alpha pattern is opinionated enough that "what's the right
  way to do X?" usually has a precedent in a sprint retro

## Bus factor (current state)

This fork has been driven by a single operator across 40+ releases
since v1. The OSS repo is open to contributions but the shipping
discipline above is non-negotiable — it's what kept zero PyPI yanks
and zero force-pushes-to-main throughout the project's lifetime.

If you're considering a larger contribution, open a discussion first
so we can sketch the sprint shape together. The "two coherent
sprint arcs in a week" pattern (v21+v22, 489 commits, 24 tags) is
the upper bound of what's been demonstrated sustainable here, and
any contribution that lands needs to fit that rhythm — small, often,
each with its own retro.

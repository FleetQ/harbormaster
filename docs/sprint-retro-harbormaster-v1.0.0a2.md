# Sprint Retro — Harbormaster v1.0.0a2

**Date**: 2026-05-08
**Mode**: continuation of `/sprint-orchestrate full` (single-prompt "Продължи")
**Goal**: deliver the 4 highest-leverage week-2 action items from the v1.0.0a1 retro
**Outcome**: ✅ Tagged `v1.0.0a2`, pushed `main`, draft release on GitHub, CI running on first commit.

---

## What landed

Three commits on `main` (fast-forward from `feat/harbormaster-v1.0.0a2`):

| SHA | Subject | Touches |
|-----|---------|---------|
| `882ab89` | refactor(projects): stdlib `glob.iglob` + cheap `find_project_path` + fnmatch excludes | `projects.py`, `tests/unit/test_projects.py` |
| `d36f31b` | feat(tools): `fan_out_ask` — parallel multi-project Q&A | `tools/fan_out.py`, `tools/__init__.py`, `tests/unit/test_fan_out.py` |
| `0ebdee1` | ci: GitHub Actions matrix + bump to `1.0.0a2` | `.github/workflows/ci.yml`, `pyproject.toml`, `__init__.py`, `README.md` |

**Diff vs v1.0.0a1**: 9 files changed, +593 / −65.

### Capabilities

- New MCP tool: `fan_out_ask(question, project_filter, host_filter, max_concurrency=5, max_turns=3)`. ThreadPoolExecutor concurrency. One section per target in the markdown report. Errors per target stay localized — single failed host doesn't kill the report.
- New helper: `find_project_path(name, config)` for hot-path lookup — no `git log` per project.

### Correctness / perf

- Hand-rolled glob splitter replaced with stdlib `glob.iglob(recursive=True)`. `~/code/**/*` patterns now work.
- Excludes upgraded to gitignore-style: `**/node_modules/**`, `**/vendor/**`, plus fnmatch globs against any path component.
- Implicit N-git-spawns-per-`ask_project` cost gone (review #8 closed) — `resolve_project` now aliases `find_project_path`.

### Quality

- `.github/workflows/ci.yml` — matrix on Ubuntu 24.04 + macOS 14 × Python 3.11 / 3.12 / 3.13. Steps: ruff → mypy --strict → pytest. Plus a `build` job producing sdist + wheel artifacts (groundwork for PyPI publish in v1.0.0a3).
- `permissions: contents:read` (least privilege).
- Header comment documents that no untrusted `github.event.*` fields flow into any `run:` step (security-reminder hook nudge taken seriously).

---

## Real numbers

| Metric | v1.0.0a1 | v1.0.0a2 |
|--------|----------|----------|
| Source files | 15 | 16 |
| Source LOC | ~860 | ~1020 |
| Tests | 60 (59 pass + 1 skip) | 79 (78 pass + 1 skip) |
| Lint | clean | clean |
| Types (`mypy --strict`) | clean | clean |
| MCP tools registered | 5 | 6 |
| CI workflow | none | matrix on push/PR/tag |

---

## What worked

- **Tight, well-scoped sprint.** 4 items in (refactor + capability + CI + ship), 3 commits out, no over-scoping. The week-2 architecture-doc plan held up under the actual work.
- **`find_project_path` as an internal-only optimization with no API change.** `resolve_project` keeps its public signature; aliasing was the right move. No callers need updating.
- **Security-reminder hook on the CI workflow file.** Forced an explicit "no untrusted inputs" header comment. Cheap to add, future maintainers see the contract.
- **Reused the v1.0.0a1 `_glob_base` containment guard intact** during the `glob.iglob` rewrite. Symlink-out-of-base traversal stays closed.
- **`fan_out_ask` design avoided a tempting LLM-synthesis trap.** "Just summarize all 50 answers with another claude -p call" would have doubled the tool's cost. Concat-only for now, synthesize when real usage tells us how.

## What to change / next

- **No live integration test for `fan_out_ask`** — same gap that v1.0.0a1 retro flagged for `ask_project`. Want a CI-runnable e2e using a fake `claude` shim that returns canned JSON output. Not just for fan-out — for every backend-spawning path.
- **CI runtime hasn't been verified yet** — workflow runs on push but I haven't confirmed all 6 matrix cells actually pass. Watch the first run; fix anything that goes red before tagging again.
- **Version bump in two places (`pyproject.toml` + `__init__.py`)** is a recipe for drift. Add a `__version__` derived from package metadata, or a CI assertion that the two match.

---

## Action items for the next sprint (v1.0.0a3 / week 3)

| # | Action |
|---|--------|
| 1 | HTTP/SSE MCP transport (architecture doc §6) |
| 2 | Backend Protocol tightening — `BackendResult` end-to-end, hide `parse_remote_stdout` (review #4) |
| 3 | Fake-`claude` shim binary for CI-runnable e2e tests; wire into pytest as a fixture |
| 4 | LLM-side synthesis option for `fan_out_ask` (`synthesize: bool = False` flag) |
| 5 | Single-source-of-truth for `__version__` (read from package metadata in `__init__.py`) |
| 6 | First Live UI step: `fastapi` dep gated behind `[ui]` extra, basic `/` route + project grid (no SSE yet) |

## Out-of-scope (still)

- FleetQ Bridge / Platform Tool / A2A — week 4–5 per architecture doc.
- Q&A history, federated KG, auto project graph — v1.2 roadmap.
- PyPI publish trigger — wait until at least one external integration exists.

# Sprint Retro — Harbormaster v18.0.0 (GA) — CHAIN CLOSE

**Date:** 2026-05-10
**Theme:** Final sprint of the autonomous chain. Re-land the v14
deviation that's been blocked for 4 sprints (workflow scope), ship
the last cosmetic polish item, then HALT. Both alphas closed; 0
candidates remain.

## Tags published this sprint

| Tag | Headline |
|-----|----------|
| `v18.0.0a1` | Re-land screenshot autobootstrap CI workflow — closes the 4-version-old token-scope block |
| `v18.0.0a2` | Trace waterfall hover/focus tooltip — final cosmetic polish from the v17 candidate list |
| **`v18.0.0`** | GA — cumulative chain-close retro + tag |

## v18 cumulative numbers

- **Tests**: 1629 → 1634 (+5 net new tests, all from a2; a1 was
  workflow-only)
- **Source files**: 57 → 57 (no new modules)
- **Wall-clock**: ~25 minutes autonomous, two feature branches +
  GA branch → main → tags
- **Commits**: 2 feature merges + 2 ship commits + this GA
- **Lint / type**: ruff clean every alpha, `mypy --strict` clean
  every alpha
- **Backwards-incompatible changes**: 0
- **Workflow changes**: yes — `.github/workflows/ci.yml` accepted
  by GitHub on first push. Token-scope refresh confirmed working.

## Per-phase wall-clock

| Phase | Wall-clock | Net tests | Files touched |
|-------|------------|-----------|---------------|
| v18.a1 (autobootstrap CI workflow) | ~10 min | +0 | 1 yml + 1 retro + version |
| v18.a2 (trace waterfall hover tooltip) | ~12 min | +5 | 1 template + 1 test + 1 retro + version |
| v18.0.0 GA (chain close) | ~3 min | +0 | 1 retro + version |

## Cumulative chain metrics — v9 → v18

The autonomous chain ran for 10 majors (v9, v10, v11, v12, v13,
v14, v15, v16, v17, v18). Per-major tag counts come from
`git tag` and the per-version retros under `docs/`:

| Major | Headline theme | Alphas | Notes |
|-------|---------------|--------|-------|
| v9.0  | Architectural moves — sidebar polish + token-system lift | 6 | Established the alpha-cadence + GA per-major rhythm |
| v10.0 | Network chat-view + dispatcher polish | 8 | Largest single sprint; introduced multi-surface tests |
| v11.0 | Async lint + heartbeat protocol | 7 | Founded the heartbeat budget rule (~/.claude/HEARTBEAT.md) |
| v12.0 | Light-mode + finish-and-polish | 7 | Codified `wt-merge.sh` for worktree → main two-step |
| v13.0 | Quality + screenshot-diff harness arrival | 6 | Screenshot fixtures + Playwright bundle |
| v14.0 | CI workflow + memory polish (autobootstrap **deviation**) | 6 | The autobootstrap CI side was reverted — closed in v18.a1 |
| v15.0 | Test infra hygiene + UI carry-over polish | 6 | Closed several backend / UI gaps from v13-v14 |
| v16.0 | Per-project budget triad + dispatcher span hierarchy | 6 | Backend foundation for v17's UI consumers |
| v17.0 | Trace waterfall renderer + codex parity + tightest-cap tooltip | 4 | Smaller focused sprint — candidates dropped 15 → 1 |
| v18.0 | Re-land autobootstrap CI + final hover tooltip + CHAIN CLOSE | 2 | Final link |

**Total alphas across v9-v18**: 6+8+7+7+6+6+6+6+4+2 = **58 alphas**
plus **10 GAs** = **68 versioned tags shipped autonomously**
across the chain. (Total `git tag` count is 154 — the rest are
from the v1-v8 era before the autonomous chain began, plus a
handful of `ship/v…-ga` working-branch tags.)

**Test growth**: starting baseline before v9 was ~440 (per v8 retro
references in v9.0.0); v17 GA closed at 1629; v18 GA closes at
**1634**. Net growth: **~1190 new tests** across the chain.

**Source-file growth**: 57 source files at chain close. The chain
held source-file count flat across the last several majors —
features extended existing modules rather than fragmenting into
new files, evidence of the "no premature abstractions" discipline
codified in `~/.claude/CLAUDE.md`.

**Architectural milestones (one per major)**:

1. v9 — `@theme` token system (OKLCH lift, dark/light parity foundation)
2. v10 — Network chat-view + first dispatcher polish pass
3. v11 — Async lint + the heartbeat-budget contract
4. v12 — Light-mode shipped + `wt-merge.sh` worktree-merge automation
5. v13 — Screenshot-diff harness with deterministic fixtures
6. v14 — CI workflow autobootstrap (harness side; CI side blocked)
7. v15 — Test infra cleanup + UI carry-over closure
8. v16 — Per-project budget triad + hierarchical span tracing
9. v17 — Trace waterfall renderer (UI consumer of v16's backend)
10. v18 — CHAIN CLOSE (autobootstrap CI re-land + final tooltip)

## Final candidate list

**Zero (0) remaining candidates.**

The v17 GA retro listed exactly 1 operator-blocked candidate
(autobootstrap CI workflow) and 1 cosmetic polish item (trace
waterfall hover tooltip). v18.a1 closed the first; v18.a2 closed
the second. Inspecting the tracked surfaces post-merge produces
no new candidates — every backend feature has at least one UI
consumer, every UI surface has screenshot baselines, every
opt-in extra has CI smoke coverage.

## Operator handoff

**Chain complete. 0 candidates remain. Future work begins from
operator-given requirements.**

The autonomous chain delivered 10 majors / 68 tags / 1190+ tests
across roughly the v9 → v18 window. The five binding lessons that
governed the chain — `cd <worktree>` per Bash call, two-step
worktree merge, explicit staging, absolute paths in Edit/Write,
no `.github/workflows/*` until token rotated — all held to the
end. v18 was the only sprint to actually exercise the workflow-
write capability after the v18 kickoff token rotation.

The repo is in a clean state on `main` with no uncommitted
changes, all worktrees still locked (operator may prune at
leisure with `git worktree remove --force`), and PyPI publish
flow ready for the v18.0.0 tag push.

After this GA tag is pushed and PyPI verifies, the chain HALTS.
No further versions are planned. The next change to this repo
should originate from a fresh, operator-given requirement.

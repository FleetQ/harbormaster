#!/usr/bin/env bash
# scripts/wt-merge.sh — push current worktree branch and merge it into
# the parent repo's main without leaving the worktree.
#
# v12.0.0a5: codifies the worktree-to-main two-step merge flow learned
# from v11. Background:
#
#   - Each phase of an autonomous sprint runs inside a git worktree
#     (.claude/worktrees/agent-…) so the parent main checkout stays
#     free for the operator's parallel work.
#   - When a phase is ready to ship, the worktree branch must (a) be
#     pushed as a backup and (b) merged into main on the parent
#     checkout. Doing both manually is repetitive and easy to forget.
#
# Invariants this script enforces:
#
#   1. Run from inside a worktree (rejects parent main).
#   2. Branch is non-empty and not "main" / "master".
#   3. Working tree clean (no uncommitted changes — caller must commit
#      first).
#   4. The parent repo path is detected via `git worktree list --porcelain`
#      so the script works for any worktree, not just this one.
#   5. Push uses the existing remote (no `--set-upstream` rewrite).
#   6. The parent merge uses `--no-ff` so the phase boundary stays
#      visible in `git log --oneline`. Skip-PR-default applied — no
#      `gh pr create` step.
#   7. Never force-push. Never amend.
#
# Usage:
#
#   bash scripts/wt-merge.sh                          # uses current branch name
#   bash scripts/wt-merge.sh feat/v12.0-foo           # explicit branch
#   bash scripts/wt-merge.sh --help
#
# Exit codes:
#   0  success
#   1  invariant violated (e.g. dirty tree, run from main)
#   2  push or merge failed
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage: wt-merge.sh [BRANCH]

Push the current worktree branch and merge it (--no-ff) into the
parent repo's main. Run from inside a git worktree.

  BRANCH    Branch to push + merge. Defaults to the current branch.
  --help    Show this help.

Invariants enforced:
  - Working tree must be clean (commit first).
  - Refuses to run from main / master.
  - Parent path auto-detected via `git worktree list`.
  - --no-ff merge preserves phase boundary.
  - Never force-pushes, never amends.

Exit codes:
  0  success
  1  invariant violated
  2  push or merge failed
USAGE
}

case "${1:-}" in
  --help|-h)
    usage
    exit 0
    ;;
esac

BRANCH="${1:-$(git symbolic-ref --short HEAD 2>/dev/null || true)}"
if [ -z "$BRANCH" ]; then
  echo "wt-merge: could not determine current branch (detached HEAD?)" >&2
  exit 1
fi
if [ "$BRANCH" = "main" ] || [ "$BRANCH" = "master" ]; then
  echo "wt-merge: refuse to push/merge from $BRANCH itself" >&2
  exit 1
fi

if [ -n "$(git status --porcelain)" ]; then
  echo "wt-merge: working tree not clean — commit your changes first" >&2
  git status --short >&2
  exit 1
fi

# Detect the parent repo path by walking `git worktree list --porcelain`.
# The first `worktree …` entry is the parent (main checkout); subsequent
# entries are linked worktrees. We pick the FIRST one whose branch is
# main/master AND whose path is NOT our own.
HERE="$(git rev-parse --show-toplevel)"
PARENT=""
while IFS= read -r line; do
  case "$line" in
    "worktree "*)
      candidate="${line#worktree }"
      ;;
    "branch refs/heads/main"|"branch refs/heads/master")
      if [ "$candidate" != "$HERE" ]; then
        PARENT="$candidate"
        break
      fi
      ;;
  esac
done < <(git worktree list --porcelain)

if [ -z "$PARENT" ]; then
  echo "wt-merge: could not locate parent (main/master) checkout via" \
       "'git worktree list --porcelain'" >&2
  exit 1
fi

REMOTE="${REMOTE:-origin}"

echo "wt-merge: pushing $BRANCH to $REMOTE (backup)…"
if ! git push "$REMOTE" "$BRANCH"; then
  echo "wt-merge: push failed" >&2
  exit 2
fi

echo "wt-merge: merging $BRANCH into main at $PARENT…"
# Use a subshell so the cd doesn't leak even if the script is sourced.
(
  cd "$PARENT"
  if ! git merge --no-ff "$BRANCH" \
       -m "Merge $BRANCH"; then
    echo "wt-merge: merge into $PARENT failed — resolve manually" >&2
    exit 2
  fi
) || exit 2

echo "wt-merge: done. Now bump __version__ + write retro + tag in $PARENT."

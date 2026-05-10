#!/usr/bin/env bash
# v16.0.0a2: one-shot helper to install the pre-commit hooks.
#
# `uv` does not currently expose a post-sync hook, so this script is
# the documented one-liner contributors run after the first
# `uv sync --extra dev`. Idempotent — pre-commit re-installs cleanly.
#
# Usage:
#
#   bash scripts/post_sync_install_hooks.sh
#
# Picks the pre-commit binary in this order:
#
#   1. .venv/bin/pre-commit (the venv that just got synced)
#   2. $(command -v pre-commit) (system / pipx fallback)
#
# Exit codes:
#   0 — hooks installed (or already installed)
#   1 — neither candidate binary was found
#   2 — pre-commit install itself failed
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

PC_BIN=""
if [ -x "$REPO_ROOT/.venv/bin/pre-commit" ]; then
  PC_BIN="$REPO_ROOT/.venv/bin/pre-commit"
elif command -v pre-commit >/dev/null 2>&1; then
  PC_BIN="$(command -v pre-commit)"
fi

if [ -z "$PC_BIN" ]; then
  echo "post_sync_install_hooks: pre-commit not found. Run \`uv sync --extra dev\` first." >&2
  exit 1
fi

if ! "$PC_BIN" install; then
  echo "post_sync_install_hooks: \`$PC_BIN install\` failed" >&2
  exit 2
fi

echo "post_sync_install_hooks: hooks installed via $PC_BIN"

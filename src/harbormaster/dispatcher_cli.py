"""`harbormaster-mcp dispatcher ...` subcommand (v6.0.0a6).

Currently exposes one operation, `status`, which prints the runtime
state of the agent.request → MCP dispatcher pool:

  * SAFE_FOR_PARALLEL set (sorted)
  * dispatcher_max_workers config
  * dispatcher_unsafe_tools deny list
  * Effective allowlist (SAFE_FOR_PARALLEL minus deny list)

Wire:

    harbormaster-mcp dispatcher status [--config PATH]

Mirrors the v2.0.1 `plugins list` pattern. Always exits 0 on a
successful introspection; 1 only on a config / setup error.
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from harbormaster.config import load_config
from harbormaster.fleetq.dispatcher import SAFE_FOR_PARALLEL

logger = logging.getLogger(__name__)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="harbormaster-mcp dispatcher",
        description="Inspect the agent.request dispatcher's pool config.",
    )
    sub = parser.add_subparsers(dest="action", required=True)

    p_status = sub.add_parser(
        "status",
        help="Print the SAFE_FOR_PARALLEL allowlist + deny list + effective set.",
    )
    p_status.add_argument(
        "--config",
        type=str,
        default=None,
        help=(
            "Path to harbormaster.toml. Default: usual config search "
            "(./.harbormaster.toml then $XDG_CONFIG_HOME/harbormaster/config.toml)."
        ),
    )
    return parser


def _print_status(args: argparse.Namespace) -> int:
    try:
        config_path = Path(args.config) if args.config else None
        config = load_config(config_path)
    except Exception as e:  # noqa: BLE001 - surface as exit 1
        print(f"Error loading config: {e}", file=sys.stderr)
        return 1

    deny = frozenset(config.fleetq.dispatcher_unsafe_tools or [])
    allow = frozenset(SAFE_FOR_PARALLEL)
    effective = allow - deny

    print(f"dispatcher_max_workers: {config.fleetq.dispatcher_max_workers}")
    if config.fleetq.dispatcher_max_workers <= 1:
        print(
            "  → pool is single-worker; per-tool safety map is informational only."
        )

    print()
    print(f"SAFE_FOR_PARALLEL ({len(allow)} tools):")
    for name in sorted(allow):
        print(f"  ✓ {name}")

    print()
    if deny:
        print(f"dispatcher_unsafe_tools deny list ({len(deny)} tools):")
        for name in sorted(deny):
            mark = "(in allowlist)" if name in allow else "(unknown tool)"
            print(f"  ✗ {name}  {mark}")
    else:
        print("dispatcher_unsafe_tools deny list: (empty)")

    print()
    print(f"Effective parallel set ({len(effective)} tools):")
    for name in sorted(effective):
        print(f"  ✓ {name}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.action == "status":
        return _print_status(args)
    parser.error(f"unknown action: {args.action!r}")
    return 2  # unreachable — argparse exits before this

"""`harbormaster-mcp plugins ...` subcommand (v2.0.1).

Currently exposes one operation, `list`, which probes the
`harbormaster.tools` entry-point group across installed distributions
and prints a categorized status table:

  * loaded         — discovered AND in [plugins].allow → register() called
  * not-allowlisted — discovered but NOT in [plugins].allow → skipped
  * missing        — listed in [plugins].allow but no matching entry point
                     installed (helps spot typos / forgotten pip installs)

Wire:

    harbormaster-mcp plugins list [--config PATH]

Always exits 0 on a successful introspection (even when [plugins].enabled
is false — the operator may be inspecting which plugins WOULD load).
Exits 1 only on a config / setup error.
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from harbormaster.config import load_config
from harbormaster.plugins import (
    _entry_point_distribution_name,
    discover_entry_points,
)

logger = logging.getLogger("harbormaster.plugins_cli")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="harbormaster-mcp plugins",
        description=(
            "Introspect harbormaster MCP plugins discovered through the "
            "`harbormaster.tools` entry-point group."
        ),
    )
    sub = parser.add_subparsers(dest="op", required=True)
    list_p = sub.add_parser("list", help="List discovered plugins + status.")
    list_p.add_argument(
        "--config",
        type=str,
        default=None,
        help="Path to config TOML. Same search order as `harbormaster-mcp`.",
    )
    return parser


def _list(config_path: Path | None) -> int:
    config = load_config(config_path)
    enabled = config.plugins.enabled
    allowlist = set(config.plugins.allow)
    eps = discover_entry_points()

    discovered: list[tuple[str, str | None]] = []
    seen_dists: set[str] = set()
    for ep in eps:
        dist = _entry_point_distribution_name(ep)
        if dist is not None:
            seen_dists.add(dist)
        discovered.append((ep.name, dist))

    print(f"[plugins].enabled = {enabled}")
    print(f"[plugins].allow   = {sorted(allowlist) if allowlist else '[]'}")
    print(f"discovered entry points: {len(discovered)}")
    print()

    if not discovered and not allowlist:
        print("(no entry points and empty allowlist — nothing to do)")
        return 0

    print(f"{'STATUS':<18} {'DIST NAME':<35} ENTRY POINT")
    print("-" * 80)

    for ep_name, dist in discovered:
        if dist is None:
            status = "no-dist-name"
        elif not enabled:
            status = "disabled"
        elif dist in allowlist:
            status = "loaded"
        else:
            status = "not-allowlisted"
        print(f"{status:<18} {(dist or '<unknown>'):<35} {ep_name}")

    missing = sorted(allowlist - seen_dists)
    for dist in missing:
        print(f"{'missing':<18} {dist:<35} (no entry point installed)")

    return 0


def main(argv: list[str] | None = None) -> int:
    """Entry point invoked by `__main__.main` when the first positional
    argument is `plugins`."""
    parser = _build_parser()
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])

    logging.basicConfig(
        level=logging.WARNING,
        format="%(asctime)s %(levelname)-7s %(name)s — %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    config_path = Path(args.config) if args.config else None
    if args.op == "list":
        return _list(config_path)
    parser.error(f"unknown plugins operation: {args.op!r}")
    return 1

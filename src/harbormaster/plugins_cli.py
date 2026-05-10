"""`harbormaster-mcp plugins ...` subcommand (v2.0.1).

Currently exposes one operation, `list`, which probes the
`harbormaster.tools` entry-point group across installed distributions
and prints a categorized status table:

  * loaded         — discovered AND in [plugins].allow → register() called
  * not-allowlisted — discovered but NOT in [plugins].allow → skipped
  * missing        — listed in [plugins].allow but no matching entry point
                     installed (helps spot typos / forgotten pip installs)

Wire:

    harbormaster-mcp plugins list [--config PATH] [--json]

Always exits 0 on a successful introspection (even when [plugins].enabled
is false — the operator may be inspecting which plugins WOULD load).
Exits 1 only on a config / setup error.

v14.0.0a6: ``--json`` emits a single JSON object so the cross-host
plugin-discovery flow (``harbormaster.plugins.query_remote_plugins``)
can shell out to this same CLI on a remote host and parse the result
deterministically. The text format is preserved byte-for-byte without
``--json``.
"""
from __future__ import annotations

import argparse
import json
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
    list_p.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help=(
            "Emit a single JSON object with the same shape as "
            "GET /api/plugins ({enabled, allow, discovered_count, plugins}). "
            "Used by the v14.0.0a6 cross-host discovery flow."
        ),
    )
    return parser


def _list_payload(config_path: Path | None) -> dict[str, object]:
    """Build the same shape as GET /api/plugins.

    Centralised so the JSON CLI output and the HTTP endpoint stay in
    lockstep — the v14.a6 cross-host flow depends on the JSON shape
    matching the local API contract.
    """
    config = load_config(config_path)
    enabled = config.plugins.enabled
    allowlist = set(config.plugins.allow)
    eps = discover_entry_points()

    rows: list[dict[str, object]] = []
    seen: set[str] = set()
    for ep in eps:
        dist = _entry_point_distribution_name(ep)
        if dist is not None:
            seen.add(dist)
        if dist is None:
            status = "no-dist-name"
        elif not enabled:
            status = "disabled"
        elif dist in allowlist:
            status = "loaded"
        else:
            status = "not-allowlisted"
        rows.append({"status": status, "dist_name": dist, "entry_point": ep.name})

    for dist in sorted(allowlist - seen):
        rows.append(
            {"status": "missing", "dist_name": dist, "entry_point": None}
        )

    return {
        "enabled": enabled,
        "allow": sorted(allowlist),
        "discovered_count": len(eps),
        "plugins": rows,
    }


def _list(config_path: Path | None, *, json_output: bool = False) -> int:
    payload = _list_payload(config_path)
    if json_output:
        sys.stdout.write(json.dumps(payload, indent=2) + "\n")
        return 0

    enabled = payload["enabled"]
    allowlist = payload["allow"]
    rows = payload["plugins"]
    assert isinstance(rows, list)

    print(f"[plugins].enabled = {enabled}")
    print(f"[plugins].allow   = {allowlist if allowlist else '[]'}")
    print(f"discovered entry points: {payload['discovered_count']}")
    print()

    if not rows:
        print("(no entry points and empty allowlist — nothing to do)")
        return 0

    print(f"{'STATUS':<18} {'DIST NAME':<35} ENTRY POINT")
    print("-" * 80)

    for row in rows:
        status = str(row["status"])
        dist = row["dist_name"]
        ep_name = row["entry_point"]
        dist_str = str(dist) if dist else "<unknown>"
        ep_display = (
            str(ep_name) if ep_name is not None
            else "(no entry point installed)"
        )
        print(f"{status:<18} {dist_str:<35} {ep_display}")

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
        return _list(config_path, json_output=args.json_output)
    parser.error(f"unknown plugins operation: {args.op!r}")
    return 1

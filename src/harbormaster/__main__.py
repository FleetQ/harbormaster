"""Entry point: `python -m harbormaster` and the `harbormaster-mcp` console script.

Supports three MCP transports:

  --transport stdio              (default; for Claude Code / Desktop)
  --transport sse                (legacy SSE — deprecated upstream but widely
                                  supported by current MCP clients)
  --transport streamable-http    (current HTTP+SSE replacement; preferred for
                                  remote clients once your client supports it)

For SSE / streamable-http, --host and --port control the bind address. v1.0
defaults --host to 127.0.0.1 — exposing on 0.0.0.0 currently has no auth
layer in front of it (auth lands in v1.1+).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from harbormaster import __version__
from harbormaster.config import load_config
from harbormaster.server import build_server


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="harbormaster-mcp",
        description=(
            "Harbormaster — MCP server that routes Q&A across your projects, "
            "locally or over SSH. Part of the FleetQ ecosystem."
        ),
    )
    parser.add_argument(
        "-V", "--version", action="version", version=__version__
    )
    parser.add_argument(
        "--transport",
        choices=["stdio", "sse", "streamable-http"],
        default="stdio",
        help="MCP transport. Default: stdio (for Claude Code / Desktop).",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help=(
            "Bind address for SSE / streamable-http. Default: 127.0.0.1 "
            "(localhost only; v1.0 has no auth layer)."
        ),
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help=(
            "Port for SSE / streamable-http. Default: server.mcp_http_port "
            "from config (7532)."
        ),
    )
    parser.add_argument(
        "--config",
        type=str,
        default=None,
        help=(
            "Path to config TOML. Default search: ./.harbormaster.toml then "
            "$XDG_CONFIG_HOME/harbormaster/config.toml then built-in defaults."
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)

    config_path = Path(args.config) if args.config else None
    config = load_config(config_path)
    mcp = build_server(config)

    if args.transport == "stdio":
        mcp.run()
        return 0

    # SSE / streamable-http: configure FastMCP transport settings then run.
    port = args.port if args.port is not None else config.server.mcp_http_port
    mcp.settings.host = args.host
    mcp.settings.port = port
    mcp.run(transport=args.transport)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

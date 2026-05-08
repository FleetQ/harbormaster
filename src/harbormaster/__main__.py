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
import json
import logging
import os
import sys
from pathlib import Path

from harbormaster import __version__
from harbormaster.config import HarbormasterConfig, load_config
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
            "Bind address for SSE / streamable-http. Default: 127.0.0.1. "
            "Auth is required for HTTP transports — see --auth-token-env."
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
    parser.add_argument(
        "--auth-token-env",
        default="HARBORMASTER_MCP_TOKEN",
        help=(
            "Env var holding the bearer token for HTTP transports. Required "
            "when --transport != stdio. Default: HARBORMASTER_MCP_TOKEN."
        ),
    )
    parser.add_argument(
        "--log-format",
        choices=["text", "json"],
        default="text",
        help=(
            "Log output format. 'text' for human-readable (default); "
            "'json' for one-line JSON per record (good under journalctl/Docker)."
        ),
    )
    return parser


class _JsonLogFormatter(logging.Formatter):
    """Single-line JSON per log record. No structlog dep — stdlib only."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname.lower(),
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def _configure_logging(level: str, fmt: str) -> None:
    """Set up the root logger.

    `level` comes from config.server.log_level (Literal-validated by pydantic).
    `fmt` comes from --log-format CLI flag.
    """
    handler = logging.StreamHandler(sys.stderr)
    if fmt == "json":
        handler.setFormatter(_JsonLogFormatter())
    else:
        handler.setFormatter(
            logging.Formatter(
                fmt="%(asctime)s %(levelname)-7s %(name)s — %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )
    root = logging.getLogger()
    # Replace any pre-existing handlers (so re-runs in long-lived processes
    # don't duplicate output).
    for h in list(root.handlers):
        root.removeHandler(h)
    root.addHandler(handler)
    root.setLevel(level.upper())


def _maybe_start_fleetq_bridge(config: HarbormasterConfig):  # type: ignore[no-untyped-def]
    """Start the FleetQ Bridge heartbeat thread if config.fleetq enables it.

    Returns the HeartbeatLoop instance (or None if disabled / [fleetq] extra
    not installed / token missing). Caller is responsible for stop()ing it
    on shutdown.
    """
    if not (config.fleetq.enabled and config.fleetq.register_as_bridge):
        return None

    api_token = os.environ.get(config.fleetq.api_token_env, "").strip()
    if not api_token:
        print(
            f"Warning: [fleetq] enabled but ${config.fleetq.api_token_env} is empty. "
            f"Skipping FleetQ bridge registration. Set the env var to a Sanctum "
            f"token with team:<uuid> ability to enable.",
            file=sys.stderr,
        )
        return None

    try:
        from harbormaster.fleetq import BridgeClient, HeartbeatLoop, build_manifest
    except ImportError as e:
        print(
            f"Warning: [fleetq] enabled but the [fleetq] extra is not installed "
            f"(missing: {e.name}). Reinstall with: pipx install 'harbormaster-mcp[fleetq]'",
            file=sys.stderr,
        )
        return None

    import socket

    client = BridgeClient(
        base_url=config.fleetq.base_url,
        api_token=api_token,
        label=f"harbormaster on {socket.gethostname()}",
        bridge_version=__version__,
    )
    endpoints = build_manifest()
    loop = HeartbeatLoop(client, endpoints, interval=config.fleetq.heartbeat_interval)
    loop.start()
    return loop


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)

    config_path = Path(args.config) if args.config else None
    config = load_config(config_path)

    _configure_logging(config.server.log_level, args.log_format)

    mcp = build_server(config)

    bridge_loop = _maybe_start_fleetq_bridge(config)

    try:
        if args.transport == "stdio":
            mcp.run()
            return 0

        # HTTP-based transport: require a bearer token before binding any port.
        from harbormaster.transport import (
            require_auth_token_or_exit,
            run_http_transport,
        )

        token = require_auth_token_or_exit(args.auth_token_env, args.transport)
        port = args.port if args.port is not None else config.server.mcp_http_port
        run_http_transport(
            mcp, transport=args.transport, host=args.host, port=port, token=token
        )
        return 0
    finally:
        if bridge_loop is not None:
            bridge_loop.stop()


if __name__ == "__main__":
    raise SystemExit(main())

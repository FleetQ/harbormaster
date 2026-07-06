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
import contextlib
import json
import logging
import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from harbormaster.fleetq.heartbeat import HeartbeatLoop
    from harbormaster.fleetq.relay import BridgeRelay

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


class _FleetQOrchestration:
    """Pair of (HeartbeatLoop, BridgeRelay | None) — caller stops both in finally."""

    def __init__(
        self,
        loop: HeartbeatLoop,
        relay: BridgeRelay | None,
    ) -> None:
        self.loop = loop
        self.relay = relay

    def stop(self) -> None:
        """Stop relay first (releases WS) then heartbeat (deregisters)."""
        if self.relay is not None:
            with contextlib.suppress(Exception):
                self.relay.stop()
        self.loop.stop()


def _maybe_start_fleetq_bridge(config: HarbormasterConfig, mcp: Any = None):  # type: ignore[no-untyped-def]
    """Start the FleetQ Bridge heartbeat + (optional) relay subscriber.

    Returns a _FleetQOrchestration with .stop() that cleans up both, or None
    when integration is disabled / not installed / missing token.

    When ``mcp`` is provided, an :class:`MCPDispatcher` is wired into the
    relay's ``chunk_handler`` so inbound ``agent.request`` events route
    through the local FastMCP tool registry (v3.0.0a1).
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
        from harbormaster.fleetq import (
            BridgeClient,
            BridgeRelay,
            BridgeStateWriter,
            HeartbeatLoop,
            MCPDispatcher,
            build_manifest,
        )
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
    state_writer = BridgeStateWriter()
    # Pass build_manifest as the drift detector so that any future change in
    # what harbormaster announces (new MCP server discovered locally, hosts
    # added at runtime, etc.) is reflected on FleetQ without a process
    # restart. Today the manifest is static so this is a no-op in practice.
    loop = HeartbeatLoop(
        client,
        endpoints,
        interval=config.fleetq.heartbeat_interval,
        endpoints_factory=build_manifest,
        state_writer=state_writer,
    )
    loop.start()

    relay = None
    response = loop.last_response
    if loop.registered and response and response.reverb_app_key and response.reverb_relay_url:
        try:
            chunk_handler = (
                MCPDispatcher(mcp).dispatch if mcp is not None else None
            )
            relay = BridgeRelay(
                base_url=config.fleetq.base_url,
                api_token=api_token,
                team_id=response.team_id,
                app_key=response.reverb_app_key,
                relay_url=response.reverb_relay_url,
                chunk_handler=chunk_handler,
                state_writer=state_writer,
                dispatcher_max_workers=config.fleetq.dispatcher_max_workers,
                dispatcher_unsafe_tools=config.fleetq.dispatcher_unsafe_tools,
            )
            relay.start()
        except Exception as e:  # noqa: BLE001 - relay is best-effort in v1.0.0a8
            print(
                f"Warning: FleetQ bridge relay failed to start ({e}). "
                f"The bridge connection is registered but inbound MCP tool "
                f"calls from FleetQ will not be received.",
                file=sys.stderr,
            )
            relay = None
    elif loop.registered:
        print(
            "Note: FleetQ bridge registered, but the response did not include "
            "Reverb credentials — relay subscriber not started.",
            file=sys.stderr,
        )

    return _FleetQOrchestration(loop=loop, relay=relay)


def main(argv: list[str] | None = None) -> int:
    raw_args = sys.argv[1:] if argv is None else argv

    # Dispatch the `reembed` subcommand to its own parser before the
    # server's argparse runs (otherwise unknown args would explode).
    # Keeps backward compat: bare `harbormaster-mcp` still launches the
    # server unchanged.
    if raw_args and raw_args[0] == "reembed":
        from harbormaster.history.cli import main as reembed_main

        return reembed_main(raw_args[1:])

    if raw_args and raw_args[0] == "plugins":
        from harbormaster.plugins_cli import main as plugins_main

        return plugins_main(raw_args[1:])

    if raw_args and raw_args[0] == "dispatcher":
        # v6.0.0a6: `harbormaster-mcp dispatcher status` introspection.
        from harbormaster.dispatcher_cli import main as dispatcher_main

        return dispatcher_main(raw_args[1:])

    if raw_args and raw_args[0] == "config":
        # v14.0.0a2: `harbormaster-mcp config check` validation report.
        from harbormaster.config_cli import main as config_main

        return config_main(raw_args[1:])

    parser = _build_parser()
    args = parser.parse_args(raw_args)

    config_path = Path(args.config) if args.config else None
    config = load_config(config_path)

    _configure_logging(config.server.log_level, args.log_format)

    mcp = build_server(config)

    # The FleetQ Bridge (heartbeat + relay) and the auto-reembed worker are
    # long-lived, singleton background subsystems that belong to a persistent
    # server instance. Claude Code / Desktop spawn a fresh stdio process per
    # connection, so starting them on stdio means every session registers a
    # duplicate bridge, spams the heartbeat retry loop into the client's
    # stderr (5MB+ logs / "Server disconnected" churn seen in the field), and
    # leaves orphaned daemon threads when the client tears the pipe down.
    # Keep stdio processes as thin MCP tool surfaces; run the background
    # subsystems only under an HTTP transport, unless the operator explicitly
    # opts a long-lived stdio host into the bridge role.
    run_background_subsystems = (
        args.transport != "stdio" or config.fleetq.bridge_in_stdio
    )

    fleetq = (
        _maybe_start_fleetq_bridge(config, mcp)
        if run_background_subsystems
        else None
    )

    # v4.0.0a5: when [history] auto_reembed_on_drift is enabled, kick
    # off a background thread that walks every per-host store and
    # reembeds any with detected model drift. No-op when disabled or
    # when [history] extra is absent.
    if run_background_subsystems:
        try:
            from harbormaster.history import maybe_start_auto_reembed_thread

            maybe_start_auto_reembed_thread(config)
        except ImportError:
            pass

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
        if fleetq is not None:
            fleetq.stop()


if __name__ == "__main__":
    raise SystemExit(main())

"""Entry point for the `harbormaster-ui` console script."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from harbormaster import __version__


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="harbormaster-ui",
        description=(
            "Harbormaster Live UI — FastAPI dashboard for project discovery "
            "and (in v1.0.0a5+) live MCP query feed."
        ),
    )
    parser.add_argument("-V", "--version", action="version", version=__version__)
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Bind address. Default: 127.0.0.1 (localhost only).",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help=(
            "Bind port. Default: server.ui_port from config (7531). "
            "Picked separately from --port on harbormaster-mcp so you can "
            "run both simultaneously without collisions."
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

    try:
        import uvicorn

        from harbormaster.config import load_config
        from harbormaster.ui import create_app
    except ImportError as e:
        print(
            f"Error: harbormaster-ui needs the [ui] extra. "
            f"Install with: pipx install 'harbormaster-mcp[ui]'  "
            f"(missing: {e.name})",
            file=sys.stderr,
        )
        return 2

    config_path = Path(args.config) if args.config else None
    config = load_config(config_path)
    app = create_app(config)

    port = args.port if args.port is not None else config.server.ui_port
    uvicorn.run(app, host=args.host, port=port, log_config=None)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

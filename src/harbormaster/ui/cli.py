"""Entry point for the `harbormaster-ui` console script.

Auth policy (v1.0.0a5)
- Loopback (`--host` is 127.0.0.1 / localhost): bearer token optional.
  If `HARBORMASTER_UI_TOKEN` is set, it's enforced — opt-in even on
  localhost. If unset, the server runs open. Reasonable for solo dev.
- Public bind (`--host` is anything else): bearer token REQUIRED. Empty
  env var aborts with exit 2 and a `secrets.token_urlsafe(32)` recipe.
- Override the env var name with `--auth-token-env`.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from harbormaster import __version__

_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="harbormaster-ui",
        description=(
            "Harbormaster Live UI — FastAPI dashboard for project discovery "
            "and (in v1.0.0a6+) live MCP query feed."
        ),
    )
    parser.add_argument("-V", "--version", action="version", version=__version__)
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help=(
            "Bind address. Default: 127.0.0.1 (loopback). Bearer auth is "
            "optional on loopback, REQUIRED on any other bind — see "
            "--auth-token-env."
        ),
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help=(
            "Bind port. Default: server.ui_port from config (7531). "
            "Separate from --port on harbormaster-mcp so you can run both."
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
        default="HARBORMASTER_UI_TOKEN",
        help=(
            "Env var holding the UI bearer token. Optional on loopback, "
            "required on public bind. Default: HARBORMASTER_UI_TOKEN."
        ),
    )
    return parser


def _resolve_ui_token(args: argparse.Namespace) -> str:
    """Resolve the UI bearer token per the loopback-vs-public policy.

    Returns the token (possibly empty when loopback + unset env). Exits 2
    when the bind is public AND the env var is empty.
    """
    raw_token = os.environ.get(args.auth_token_env, "").strip()
    is_loopback = args.host in _LOOPBACK_HOSTS

    if not raw_token and not is_loopback:
        print(
            f"Error: --host {args.host} (non-loopback) requires a bearer token.\n"
            f"Set ${args.auth_token_env} to a strong secret, then re-run. Example:\n"
            f"  export {args.auth_token_env}="
            f"$(python -c 'import secrets; print(secrets.token_urlsafe(32))')\n"
            f"Or bind to --host 127.0.0.1 for local-only no-auth use.",
            file=sys.stderr,
        )
        raise SystemExit(2)

    return raw_token


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)

    try:
        import uvicorn

        from harbormaster.config import load_config
        from harbormaster.transport import build_bearer_middleware
        from harbormaster.ui import create_app
    except ImportError as e:
        print(
            f"Error: harbormaster-ui needs the [ui] extra. "
            f"Install with: pipx install 'harbormaster-mcp[ui]'  "
            f"(missing: {e.name})",
            file=sys.stderr,
        )
        return 2

    token = _resolve_ui_token(args)

    config_path = Path(args.config) if args.config else None
    config = load_config(config_path)
    app = create_app(config)

    if token:
        app.add_middleware(build_bearer_middleware(token))

    port = args.port if args.port is not None else config.server.ui_port
    uvicorn.run(app, host=args.host, port=port, log_config=None)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

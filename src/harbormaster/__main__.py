"""Entry point: `python -m harbormaster` and the `harbormaster-mcp` console script."""
from __future__ import annotations

import sys

from harbormaster import __version__
from harbormaster.config import load_config
from harbormaster.server import build_server


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] in ("--version", "-V"):
        print(__version__)
        return 0

    config = load_config()
    mcp = build_server(config)
    mcp.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

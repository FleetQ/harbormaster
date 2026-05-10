"""`harbormaster-mcp dispatcher ...` subcommand (v6.0.0a6, --json v7.0.0a4).

Currently exposes one operation, `status`, which prints the runtime
state of the agent.request → MCP dispatcher pool:

  * SAFE_FOR_PARALLEL set (sorted)
  * dispatcher_max_workers config
  * dispatcher_unsafe_tools deny list
  * Effective allowlist (SAFE_FOR_PARALLEL minus deny list)

Wire:

    harbormaster-mcp dispatcher status [--config PATH] [--json]

Mirrors the v2.0.1 `plugins list` pattern. Always exits 0 on a
successful introspection; 1 only on a config / setup error.

v7.0.0a5: ``--json`` emits a single JSON object instead of the
text format. The text format is preserved byte-for-byte (zero
breaking change). The JSON object documents the introspective
shape of the dispatcher — the canonical schema is documented in
the source of ``_status_payload``.

Note: the dispatcher is in-process and stateless from this CLI's
perspective — there is no live worker pool to query. The
``--json`` shape therefore omits ``running``, ``active_workers``,
``queue_depth``, and ``last_dispatched_at`` (those would require
a sidecar metrics endpoint that doesn't exist yet). The JSON
payload describes what an operator can configure and what the
dispatcher considers safe to parallelise.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any

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
    p_status.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help=(
            "Emit a single JSON object instead of the text format. "
            "Schema: {dispatcher_max_workers, single_worker, "
            "safe_for_parallel: [...], unsafe_tools: [...], "
            "effective_parallel_set: [...]}. The text format is "
            "preserved byte-for-byte without this flag."
        ),
    )
    p_status.add_argument(
        "--url",
        type=str,
        default=None,
        help=(
            "Optional HTTP base URL of a running harbormaster-ui "
            "instance (e.g. http://127.0.0.1:8765). When provided, "
            "the CLI fetches GET <url>/api/dispatcher/status and "
            "merges the live runtime counters (running, "
            "active_workers, queue_depth, last_dispatched_at, tools) "
            "into the JSON output. v9.0.0a2."
        ),
    )
    return parser


def _status_payload(config: Any) -> dict[str, object]:
    """Build the canonical status object — used by both text and JSON paths.

    Schema (v7.0.0a5):
      dispatcher_max_workers : int
      single_worker          : bool   # True when max_workers <= 1
      safe_for_parallel      : list[str]   # sorted
      unsafe_tools           : list[{name, in_allowlist}]   # sorted by name
      effective_parallel_set : list[str]   # sorted
    """
    deny = frozenset(config.fleetq.dispatcher_unsafe_tools or [])
    allow = frozenset(SAFE_FOR_PARALLEL)
    effective = allow - deny
    return {
        "dispatcher_max_workers": int(config.fleetq.dispatcher_max_workers),
        "single_worker": bool(config.fleetq.dispatcher_max_workers <= 1),
        "safe_for_parallel": sorted(allow),
        "unsafe_tools": [
            {"name": name, "in_allowlist": name in allow}
            for name in sorted(deny)
        ],
        "effective_parallel_set": sorted(effective),
    }


def _print_status_text(payload: dict[str, object]) -> None:
    print(f"dispatcher_max_workers: {payload['dispatcher_max_workers']}")
    if payload["single_worker"]:
        print(
            "  → pool is single-worker; per-tool safety map is informational only."
        )

    safe = payload["safe_for_parallel"]
    assert isinstance(safe, list)
    print()
    print(f"SAFE_FOR_PARALLEL ({len(safe)} tools):")
    for name in safe:
        print(f"  ✓ {name}")

    unsafe = payload["unsafe_tools"]
    assert isinstance(unsafe, list)
    print()
    if unsafe:
        print(f"dispatcher_unsafe_tools deny list ({len(unsafe)} tools):")
        for entry in unsafe:
            assert isinstance(entry, dict)
            mark = "(in allowlist)" if entry["in_allowlist"] else "(unknown tool)"
            print(f"  ✗ {entry['name']}  {mark}")
    else:
        print("dispatcher_unsafe_tools deny list: (empty)")

    eff = payload["effective_parallel_set"]
    assert isinstance(eff, list)
    print()
    print(f"Effective parallel set ({len(eff)} tools):")
    for name in eff:
        print(f"  ✓ {name}")


def _fetch_runtime_status(url: str) -> dict[str, Any] | None:
    """GET <url>/api/dispatcher/status. None when fetch fails (best-effort)."""
    import urllib.error
    import urllib.request

    endpoint = url.rstrip("/") + "/api/dispatcher/status"
    try:
        with urllib.request.urlopen(endpoint, timeout=5) as resp:  # noqa: S310
            data = json.loads(resp.read().decode("utf-8"))
            if isinstance(data, dict):
                return data
    except (urllib.error.URLError, TimeoutError, ValueError, json.JSONDecodeError):
        return None
    return None


def _print_status(args: argparse.Namespace) -> int:
    try:
        config_path = Path(args.config) if args.config else None
        config = load_config(config_path)
    except Exception as e:  # noqa: BLE001 - surface as exit 1
        print(f"Error loading config: {e}", file=sys.stderr)
        return 1

    payload: dict[str, Any] = dict(_status_payload(config))

    runtime: dict[str, Any] | None = None
    url = getattr(args, "url", None)
    if url:
        runtime = _fetch_runtime_status(url)
        if runtime is None:
            print(
                f"Warning: could not fetch runtime status from {url} "
                "— falling back to config-only output.",
                file=sys.stderr,
            )
        else:
            payload["runtime"] = runtime

    if getattr(args, "json_output", False):
        # Single-line JSON keeps it grep/jq-friendly. Indent=None
        # avoids needless whitespace in scripted pipelines.
        print(json.dumps(payload, sort_keys=True))
    else:
        _print_status_text(payload)
        if runtime is not None:
            _print_runtime_text(runtime)
    return 0


def _print_runtime_text(runtime: dict[str, Any]) -> None:
    print()
    active = runtime.get("active_workers", 0)
    queue = runtime.get("queue_depth", 0)
    print(f"Live runtime (v9.0.0a2): active_workers={active}, queue_depth={queue}")
    last = runtime.get("last_dispatched_at")
    if last is not None:
        print(f"  last_dispatched_at: {last}")
    tools = runtime.get("tools") or {}
    if isinstance(tools, dict) and tools:
        print(f"  per-tool counters ({len(tools)}):")
        for name in sorted(tools):
            c = tools[name] if isinstance(tools[name], dict) else {}
            in_flight = c.get("in_flight", 0)
            done = c.get("total_completed", 0)
            failed = c.get("total_failed", 0)
            print(
                f"    {name}: in_flight={in_flight} "
                f"completed={done} failed={failed}"
            )


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.action == "status":
        return _print_status(args)
    parser.error(f"unknown action: {args.action!r}")
    return 2  # unreachable — argparse exits before this

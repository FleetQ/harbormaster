"""`harbormaster-mcp reembed` subcommand (v2.0.0a2).

Detects embedding-model drift and re-encodes every Q&A row against the
currently configured backend. One host at a time (the user picks via
`--host` / `--all-hosts`). Runs in batches with a resumable rowid
marker; safe to interrupt.

Wire:

    harbormaster-mcp reembed [--host LABEL | --all-hosts]
                             [--batch-size N] [--no-resume]
                             [--dry-run] [--config PATH]

Always exits 0 on a successful run (even when nothing was re-embedded
because the store is fresh / vectors already up to date). Exits 1 only
on a configuration / setup error the operator must fix.
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from harbormaster.config import HarbormasterConfig, load_config
from harbormaster.history.embed import get_embedding_backend
from harbormaster.history.store import QAStore

logger = logging.getLogger("harbormaster.history.cli")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="harbormaster-mcp reembed",
        description=(
            "Re-embed every Q&A history row with the currently configured "
            "embedding backend. Use after switching `[history].fastembed_model` "
            "to bring stored vectors back into the same vector space as new "
            "queries."
        ),
    )
    parser.add_argument(
        "--config",
        type=str,
        default=None,
        help="Path to config TOML. Same search order as `harbormaster-mcp`.",
    )
    target_group = parser.add_mutually_exclusive_group()
    target_group.add_argument(
        "--host",
        default=None,
        help=(
            "Target host label (matches a configured `[hosts.<label>]`). "
            "Use 'local' or omit to target the local store."
        ),
    )
    target_group.add_argument(
        "--all-hosts",
        action="store_true",
        help="Re-embed local store + every configured `[hosts.*]` store.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=100,
        help="Rows per commit batch. Default: 100.",
    )
    parser.add_argument(
        "--no-resume",
        action="store_true",
        help=(
            "Start from rowid 0 instead of "
            "`embedding_meta.last_reembedded_rowid`. Use after a failed run "
            "where the resume marker is suspect."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Open the store, report drift status + row count, but do not "
            "re-encode anything."
        ),
    )
    return parser


def _hosts_to_process(
    config: HarbormasterConfig, host_arg: str | None, all_hosts: bool
) -> list[str | None]:
    if all_hosts:
        return [None] + list(config.hosts.keys())
    if host_arg is None or host_arg == "local":
        return [None]
    if host_arg not in config.hosts:
        raise SystemExit(
            f"Error: host '{host_arg}' is not configured. Available: "
            f"{', '.join(sorted(config.hosts.keys())) or '<none>'}"
        )
    return [host_arg]


def _process_host(
    config: HarbormasterConfig,
    host: str | None,
    *,
    batch_size: int,
    resume: bool,
    dry_run: bool,
) -> tuple[int, int]:
    """Open the store for `host`, run drift check + re-embed (unless
    dry_run). Returns `(processed, total_pending)`."""
    backend = get_embedding_backend(config)
    label = host if host is not None else "local"

    with QAStore.open(
        db_dir=config.history.db_dir,
        host=host,
        embedding_backend=backend,
        embedding_dim=config.history.embedding_dim,
    ) as store:
        meta = store.embedding_meta()
        drift = store.has_embedding_drift()
        total = store.count()
        print(
            f"[{label}] rows={total} "
            f"stored={meta.signature if meta else '<none>'}/dim="
            f"{meta.dim if meta else 0} "
            f"configured={backend.signature}/dim={config.history.embedding_dim} "
            f"drift={'yes' if drift else 'no'}"
        )
        if dry_run:
            return 0, total
        processed, pending = store.reembed(batch_size=batch_size, resume=resume)
        print(f"[{label}] reembedded {processed}/{pending} pending rows")
        return processed, pending


def main(argv: list[str] | None = None) -> int:
    """Entry point invoked by `__main__.main` when the first positional
    argument is `reembed`."""
    parser = _build_parser()
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s — %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    config = load_config(Path(args.config) if args.config else None)

    if not config.history.enabled:
        print(
            "Note: [history].enabled is false. The store may still exist on "
            "disk; proceeding with re-embed anyway. Set [history].enabled = "
            "true if you want recall to use the new vectors at runtime.",
            file=sys.stderr,
        )

    targets = _hosts_to_process(config, args.host, args.all_hosts)
    total_processed = 0
    for host in targets:
        try:
            processed, _ = _process_host(
                config,
                host,
                batch_size=args.batch_size,
                resume=not args.no_resume,
                dry_run=args.dry_run,
            )
            total_processed += processed
        except Exception:  # noqa: BLE001 - operator-facing tool, surface root cause
            logger.exception(
                "reembed failed for host=%s", host if host is not None else "local"
            )
            return 1

    print(f"Done. Total re-embedded across {len(targets)} target(s): {total_processed}")
    return 0

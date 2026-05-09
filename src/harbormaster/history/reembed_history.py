"""Rolling reembed run-history log (v7.0.0a4).

Each completed reembed run appends a record to
``~/.harbormaster/reembed_history.json``. The file holds the most
recent 50 runs (oldest pruned on append). Read by the UI panel and
the ``GET /api/history/reembed/runs`` endpoint.

Wire shape (one record):

    {
      "started_at": 1715260000.0,
      "finished_at": 1715260030.0,
      "total": 4,
      "succeeded": 3,
      "failed": 0,
      "cancelled": 1,
      "model": "fastembed:BAAI/bge-small-en-v1.5"
    }

Notes:
  * The file is created with mode 0600, matching the security-audit
    convention used for other ``~/.harbormaster/`` state files.
  * Atomic-tempfile-rename for crash-safety, same as
    ``auto_reembed._write_state``.
  * The runner never blocks on this file — failures are swallowed
    and logged. We'd rather lose one history entry than crash a
    background thread.
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any

from pydantic import BaseModel

logger = logging.getLogger(__name__)


# Cap matches the v6.0.0a4 retro recommendation: 50 is enough to cover
# a few weeks of daily reembeds without ballooning the file or making
# the UI table noisy. Bump deliberately if a use case appears.
MAX_HISTORY_RECORDS = 50

DEFAULT_HISTORY_PATH = Path.home() / ".harbormaster" / "reembed_history.json"


class ReembedRunRecord(BaseModel):
    """One completed reembed run."""

    started_at: float
    finished_at: float
    total: int = 0
    succeeded: int = 0
    failed: int = 0
    cancelled: int = 0
    model: str | None = None


def _resolve_history_path() -> Path:
    override = os.environ.get("HARBORMASTER_REEMBED_HISTORY_FILE", "").strip()
    return Path(override) if override else DEFAULT_HISTORY_PATH


def read_runs(path: Path | None = None) -> list[ReembedRunRecord]:
    """Read the run history. Returns an empty list when missing /
    malformed (the file is best-effort; never block the UI on it)."""
    history_path = path or _resolve_history_path()
    if not history_path.exists():
        return []
    try:
        raw = json.loads(history_path.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001 - corrupt file shouldn't break UI
        logger.warning(
            "read_runs: failed to parse %s (%s) — returning empty list",
            history_path,
            e,
        )
        return []
    if not isinstance(raw, list):
        return []
    out: list[ReembedRunRecord] = []
    for item in raw:
        try:
            out.append(ReembedRunRecord.model_validate(item))
        except Exception:  # noqa: BLE001 - drop bad rows, keep rest
            continue
    return out


def append_run(
    record: ReembedRunRecord, path: Path | None = None
) -> None:
    """Append one run record (atomic). Caps the file at
    ``MAX_HISTORY_RECORDS`` rows by dropping the oldest first.

    Swallows every error. The runner must never crash because of a
    bad history-file path or disk-full condition."""
    history_path = path or _resolve_history_path()
    try:
        history_path.parent.mkdir(parents=True, exist_ok=True)
        existing = read_runs(history_path)
        existing.append(record)
        # Keep the most-recent MAX_HISTORY_RECORDS entries.
        trimmed = existing[-MAX_HISTORY_RECORDS:]
        payload = json.dumps(
            [r.model_dump(mode="json") for r in trimmed],
            indent=2,
        )
        with tempfile.NamedTemporaryFile(
            "w",
            dir=str(history_path.parent),
            prefix=".reembed_history.",
            suffix=".tmp",
            delete=False,
        ) as f:
            f.write(payload)
            tmp_path = Path(f.name)
        os.replace(tmp_path, history_path)
        # Mode 0600 — security-audit convention for state files
        # under ~/.harbormaster/.
        try:
            os.chmod(history_path, 0o600)
        except OSError as e:
            logger.warning(
                "append_run: chmod 0600 failed for %s (%s) — continuing",
                history_path,
                e,
            )
    except Exception as e:  # noqa: BLE001 - never raise from a history writer
        logger.warning(
            "append_run: failed to append to %s (%s)",
            history_path,
            e,
        )


def record_from_state_and_errors(
    *,
    started_at: float,
    finished_at: float,
    total: int,
    processed: int,
    errors: list[str],
    cancelled: bool,
    model: str | None,
) -> ReembedRunRecord:
    """Build a ReembedRunRecord from the runner's local state.

    succeeded = (processed - len(errors)) when not cancelled else
                (processed - len(errors)) — same formula, the cancelled
                path doesn't affect succeeded/failed counts of hosts
                that did finish before cancel was observed.
    cancelled = total - processed when cancelled, else 0
    failed    = len(errors)
    """
    failed = len(errors)
    # processed - failed = hosts that completed without error.
    # Clamp to zero defensively; in practice processed >= failed.
    succeeded = max(0, processed - failed)
    cancelled_count = max(0, total - processed) if cancelled else 0
    return ReembedRunRecord(
        started_at=started_at,
        finished_at=finished_at,
        total=total,
        succeeded=succeeded,
        failed=failed,
        cancelled=cancelled_count,
        model=model,
    )


def _resolve_model_label(config: Any) -> str | None:
    """Compose a 'backend:model' label for the run record. Returns
    None when [history] is disabled or backend resolution fails —
    the field is informational, never load-bearing."""
    try:
        backend = config.history.embedding_backend
        model = getattr(config.history, "embedding_model", None)
        if backend == "fastembed" and model:
            return f"{backend}:{model}"
        return str(backend) if backend else None
    except Exception:  # noqa: BLE001 - history record is best-effort
        return None

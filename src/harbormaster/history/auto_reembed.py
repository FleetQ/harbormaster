"""Auto-reembed state machine + background thread (v4.0.0a5).

When ``[history] auto_reembed_on_drift = true`` and a drift is
detected on QAStore.open(), the harbormaster-mcp process can spawn
a background thread that walks every per-host store and reembeds
the rows. State is written to a JSON file (atomic) so the UI
process can render progress.

Wire shape (cross-process state file ``~/.harbormaster/reembed-state.json``):

    {
      "phase": "idle" | "running" | "done" | "failed",
      "processed": 0,
      "total": 0,
      "current_host": "local" | "<label>" | null,
      "started_at": 1715260000.0 | null,
      "finished_at": 1715260000.0 | null,
      "error": null | "<message>"
    }

The state writer + reader follow the same atomic-tempfile-rename
pattern as ``harbormaster.fleetq.state``.
"""
from __future__ import annotations

import logging
import os
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

from pydantic import BaseModel

logger = logging.getLogger(__name__)


DEFAULT_STATE_PATH = Path.home() / ".harbormaster" / "reembed-state.json"


class ReembedState(BaseModel):
    """Snapshot of the auto-reembed runner."""

    phase: str = "idle"  # idle | running | done | failed
    processed: int = 0
    total: int = 0
    current_host: str | None = None
    started_at: float | None = None
    finished_at: float | None = None
    error: str | None = None
    writer_pid: int | None = None


def _resolve_state_path() -> Path:
    override = os.environ.get("HARBORMASTER_REEMBED_STATE_FILE", "").strip()
    return Path(override) if override else DEFAULT_STATE_PATH


def _write_state(state: ReembedState, path: Path | None = None) -> None:
    """Atomic-write state JSON. Swallows every error — the runner
    must never crash because of a bad state-file path."""
    state_path = path or _resolve_state_path()
    state = state.model_copy(update={"writer_pid": os.getpid()})
    try:
        state_path.parent.mkdir(parents=True, exist_ok=True)
        payload = state.model_dump_json()
        with tempfile.NamedTemporaryFile(
            "w",
            dir=str(state_path.parent),
            prefix=".reembed-state.",
            suffix=".tmp",
            delete=False,
        ) as f:
            f.write(payload)
            tmp_path = Path(f.name)
        os.replace(tmp_path, state_path)
    except Exception as e:  # noqa: BLE001 - never raise from a writer
        logger.warning("auto_reembed: failed to write %s (%s)", state_path, e)


def read_state(path: Path | None = None) -> ReembedState:
    """Read the current reembed state. Returns a default-idle state
    when the file is missing or malformed."""
    state_path = path or _resolve_state_path()
    if not state_path.exists():
        return ReembedState()
    try:
        return ReembedState.model_validate_json(
            state_path.read_text(encoding="utf-8")
        )
    except Exception as e:  # noqa: BLE001 - corrupt file shouldn't break UI
        logger.warning(
            "read_state: failed to parse %s (%s) — returning idle",
            state_path,
            e,
        )
        return ReembedState()


def _reembed_one_host(
    *, config: Any, host: str | None, state: ReembedState
) -> tuple[int, str | None]:
    """Open the per-host store, check drift, reembed if drifted.
    Returns (processed_rows, error_message_or_None).

    Errors are caught here so a single bad host doesn't poison the
    entire auto-reembed run.
    """
    from harbormaster.history import QAStore, get_embedding_backend

    label = host if host is not None else "local"
    try:
        backend = get_embedding_backend(config)
        store = QAStore.open(
            db_dir=config.history.db_dir,
            host=host,
            embedding_backend=backend,
            embedding_dim=config.history.embedding_dim,
        )
    except Exception as e:  # noqa: BLE001 - per-host isolation
        logger.exception("auto_reembed: opening store failed for host=%s", label)
        return 0, f"open failed: {e}"

    try:
        if not store.has_embedding_drift():
            return 0, None
        # Update state to reflect we're now actually working on this host.
        state.current_host = label
        _write_state(state)
        processed, _total = store.reembed(batch_size=100, resume=True)
        return processed, None
    except Exception as e:  # noqa: BLE001 - per-host isolation
        logger.exception("auto_reembed: reembed failed for host=%s", label)
        return 0, f"reembed failed: {e}"
    finally:
        store.close()


def run_auto_reembed(config: Any, *, state_path: Path | None = None) -> None:
    """Walk local + every configured host, reembedding any with drift.

    Designed to run on a background thread. Updates the state file
    on entry, after each host, and on exit. Always finishes with
    phase ∈ {done, failed} so the UI can stop polling.
    """
    state = ReembedState(phase="running", started_at=time.time())
    _write_state(state, state_path)

    targets: list[str | None] = [None, *sorted(config.hosts.keys())]
    state.total = len(targets)
    _write_state(state, state_path)

    errors: list[str] = []
    for target in targets:
        processed, err = _reembed_one_host(
            config=config, host=target, state=state
        )
        state.processed += 1
        if err is not None:
            label = target if target is not None else "local"
            errors.append(f"{label}: {err}")
        _write_state(state, state_path)
        logger.info(
            "auto_reembed: host=%s processed_rows=%d err=%s",
            target if target is not None else "local",
            processed,
            err,
        )

    state.current_host = None
    state.finished_at = time.time()
    if errors:
        state.phase = "failed"
        state.error = "; ".join(errors)
    else:
        state.phase = "done"
        state.error = None
    _write_state(state, state_path)


def maybe_start_auto_reembed_thread(config: Any) -> threading.Thread | None:
    """Spawn the auto-reembed thread when both the config flag is set
    AND the [history] extra is installed. Returns the started thread,
    or None when the conditions aren't met (no-op / not installed).
    """
    if not (config.history.enabled and config.history.auto_reembed_on_drift):
        return None
    try:
        from harbormaster.history import (  # noqa: F401 - presence-only check
            QAStore,
        )
    except ImportError:
        logger.info(
            "auto_reembed: [history] extra not installed — skipping"
        )
        return None

    thread = threading.Thread(
        target=run_auto_reembed,
        args=(config,),
        daemon=True,
        name="auto-reembed",
    )
    thread.start()
    logger.info("auto_reembed: background thread started")
    return thread

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

    phase: str = "idle"  # idle | running | done | failed | cancelled
    processed: int = 0
    total: int = 0
    current_host: str | None = None
    started_at: float | None = None
    finished_at: float | None = None
    error: str | None = None
    writer_pid: int | None = None
    # v7.0.0a3: cooperative cancel flag. Set by request_cancel() / the
    # POST /api/history/reembed/cancel endpoint; checked by the worker
    # between hosts. Idempotent — setting it twice is fine.
    cancel_requested: bool = False


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


# v5.0.0a1: backoff schedule for transient failures during open / reembed.
# Three retries at 1s / 2s / 4s before giving up. Exponential keeps the
# total wait bounded (7s) while smoothing over momentary sqlite-busy /
# transient I/O blips.
_RETRY_BACKOFF_SECONDS: tuple[float, ...] = (1.0, 2.0, 4.0)


def _reembed_one_host(
    *, config: Any, host: str | None, state: ReembedState
) -> tuple[int, str | None]:
    """Open the per-host store, check drift, reembed if drifted.
    Returns (processed_rows, error_message_or_None).

    Errors are caught here so a single bad host doesn't poison the
    entire auto-reembed run. v5.0.0a1: open / reembed paths retry up
    to 3 times with exponential backoff on transient errors before
    surfacing a permanent failure to the runner.
    """
    from harbormaster.history import QAStore, get_embedding_backend

    label = host if host is not None else "local"

    backend = get_embedding_backend(config)
    store = None
    last_open_error: Exception | None = None
    for attempt, delay in enumerate(
        (0.0, *_RETRY_BACKOFF_SECONDS), start=1
    ):
        if delay > 0:
            time.sleep(delay)
        try:
            store = QAStore.open(
                db_dir=config.history.db_dir,
                host=host,
                embedding_backend=backend,
                embedding_dim=config.history.embedding_dim,
            )
            last_open_error = None
            break
        except Exception as e:  # noqa: BLE001 - per-host isolation
            last_open_error = e
            logger.warning(
                "auto_reembed: open attempt %d/%d failed for host=%s: %s",
                attempt,
                len(_RETRY_BACKOFF_SECONDS) + 1,
                label,
                e,
            )
    if store is None:
        return 0, f"open failed (after {len(_RETRY_BACKOFF_SECONDS) + 1} attempts): {last_open_error}"

    try:
        if not store.has_embedding_drift():
            return 0, None
        # Update state to reflect we're now actually working on this host.
        state.current_host = label
        _write_state(state)
        last_reembed_error: Exception | None = None
        for attempt, delay in enumerate(
            (0.0, *_RETRY_BACKOFF_SECONDS), start=1
        ):
            if delay > 0:
                time.sleep(delay)
            try:
                processed, _total = store.reembed(batch_size=100, resume=True)
                return processed, None
            except Exception as e:  # noqa: BLE001 - per-host isolation
                last_reembed_error = e
                logger.warning(
                    "auto_reembed: reembed attempt %d/%d failed for host=%s: %s",
                    attempt,
                    len(_RETRY_BACKOFF_SECONDS) + 1,
                    label,
                    e,
                )
        return 0, f"reembed failed (after {len(_RETRY_BACKOFF_SECONDS) + 1} attempts): {last_reembed_error}"
    finally:
        store.close()


def run_auto_reembed(config: Any, *, state_path: Path | None = None) -> None:
    """Walk local + every configured host, reembedding any with drift.

    Designed to run on a background thread. Updates the state file
    on entry, after each host, and on exit. Always finishes with
    phase ∈ {done, failed, cancelled} so the UI can stop polling.
    """
    # v7.0.0a3: preserve a pre-existing cancel flag through the
    # initial state writes. Without this, a cancel set in the tiny
    # window between trigger_manual_reembed() and the worker thread's
    # first instruction would be silently overwritten.
    pre = read_state(state_path)
    state = ReembedState(
        phase="running",
        started_at=time.time(),
        cancel_requested=pre.cancel_requested,
    )
    _write_state(state, state_path)

    targets: list[str | None] = [None, *sorted(config.hosts.keys())]
    state.total = len(targets)
    _write_state(state, state_path)

    errors: list[str] = []
    cancelled = False
    for target in targets:
        # v7.0.0a3: cooperative cancel check between hosts.
        # Re-read the state file because the cancel flag is set by a
        # different process / request handler, not by this thread.
        on_disk = read_state(state_path)
        if on_disk.cancel_requested:
            cancelled = True
            logger.info("auto_reembed: cancel requested — stopping after current host")
            break
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
    if cancelled:
        state.phase = "cancelled"
        state.error = None
    elif errors:
        state.phase = "failed"
        state.error = "; ".join(errors)
    else:
        state.phase = "done"
        state.error = None
    # Clear the cancel flag on the in-memory state we're about to
    # persist. This makes subsequent runs start clean — the next
    # trigger_manual_reembed() begins with cancel_requested=False.
    state.cancel_requested = False
    _write_state(state, state_path)

    # v7.0.0a4: append a completed-run record to the rolling history
    # log. Best-effort — the writer swallows all errors so we never
    # crash the runner thread on a history-file failure.
    try:
        from harbormaster.history.reembed_history import (
            _resolve_model_label,
            append_run,
            record_from_state_and_errors,
        )

        assert state.started_at is not None
        assert state.finished_at is not None
        record = record_from_state_and_errors(
            started_at=state.started_at,
            finished_at=state.finished_at,
            total=state.total,
            processed=state.processed,
            errors=errors,
            cancelled=cancelled,
            model=_resolve_model_label(config),
        )
        append_run(record)
    except Exception as e:  # noqa: BLE001 - history is best-effort
        logger.warning("auto_reembed: failed to log run history (%s)", e)


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


def trigger_manual_reembed(
    config: Any, *, state_path: Path | None = None
) -> tuple[bool, str | None]:
    """v6.0.0a1: kick off an auto-reembed run on demand.

    Used by the UI's POST /api/history/reembed endpoint. Returns
    (started, error_message). Refuses to start a second run when one
    is already in progress (idempotent under double-click + cross-tab
    triggers).

    Unlike maybe_start_auto_reembed_thread, this does NOT honour the
    [history] auto_reembed_on_drift gate — operator action is the gate.
    The [history] enabled gate still applies (no point reembedding
    when the store is disabled).
    """
    if not config.history.enabled:
        return False, "[history] is disabled — nothing to reembed"
    try:
        from harbormaster.history import QAStore  # noqa: F401
    except ImportError:
        return False, "[history] extra not installed"

    current = read_state(state_path)
    if current.phase == "running":
        return False, "auto-reembed already in progress"

    thread = threading.Thread(
        target=run_auto_reembed,
        args=(config,),
        kwargs={"state_path": state_path} if state_path else {},
        daemon=True,
        name="auto-reembed-manual",
    )
    thread.start()
    logger.info("auto_reembed: manual trigger — background thread started")
    return True, None


def request_cancel(
    state_path: Path | None = None,
) -> tuple[bool, ReembedState]:
    """v7.0.0a3: cooperative cancel for an in-flight reembed run.

    Returns ``(was_running, current_state_after_request)``. The flag
    is honoured by ``run_auto_reembed`` between hosts (cancel never
    interrupts the in-progress host's reembed; a single host is
    treated as the smallest atomic unit so we don't leave half-
    processed sqlite-vec rows behind).

    Idempotent: cancelling a non-running reembed is a no-op that
    returns ``(False, current_state)``. The flag is also cleared
    automatically by the runner on completion, so the next triggered
    run starts clean.
    """
    current = read_state(state_path)
    if current.phase != "running":
        return False, current
    cancelled_state = current.model_copy(update={"cancel_requested": True})
    _write_state(cancelled_state, state_path)
    logger.info("auto_reembed: cancel flag set on running reembed")
    return True, cancelled_state

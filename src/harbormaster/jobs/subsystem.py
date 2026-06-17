"""Process-singleton init for the async delegate JobStore + JobWorker
(v22.0.0a2).

Tools call :func:`get_subsystem` instead of constructing a store /
worker themselves. First call opens the SQLite store, runs orphan
recovery (re-queues safe read-only rows left ``running`` by a previous
process, fails the rest), starts the worker thread, and returns the
bundle. Subsequent calls return the cached bundle.

``shutdown_subsystem`` exists primarily for tests — production code
relies on the daemon-thread worker exiting when the process dies.
"""
from __future__ import annotations

import logging
import os
import threading
from dataclasses import dataclass
from pathlib import Path

from harbormaster.config import HarbormasterConfig
from harbormaster.jobs.broadcaster import JobEventBroadcaster
from harbormaster.jobs.store import JobStore
from harbormaster.jobs.worker import JobWorker

_LOG = logging.getLogger(__name__)

_lock = threading.Lock()
_singleton: Subsystem | None = None


@dataclass
class Subsystem:
    store: JobStore
    workers: list[JobWorker]
    broadcaster: JobEventBroadcaster

    @property
    def worker(self) -> JobWorker:
        """v22→v24 compat shim: existing code paths read ``sub.worker``
        as the singular worker. With v24.0.0a1 multi-worker, return
        the first worker — sufficient for read-only inspection
        (``is_alive``, etc.). For lifecycle control, use ``workers``.
        """
        return self.workers[0]

    def shutdown(self) -> None:
        for w in self.workers:
            w.stop()
        self.store.close()


def _resolve_db_path(config: HarbormasterConfig) -> Path:
    # Reuse the [history] db_dir if available — that's where the
    # operator already keeps qa_local.db. Falls back to ~/.harbormaster.
    # Tests can override via $HARBORMASTER_JOBS_DB.
    override = os.environ.get("HARBORMASTER_JOBS_DB")
    if override:
        return Path(override).expanduser()
    if config.history.enabled and config.history.db_dir:
        return Path(config.history.db_dir).expanduser() / "delegated_jobs.db"
    return Path("~/.harbormaster/delegated_jobs.db").expanduser()


def get_subsystem(config: HarbormasterConfig) -> Subsystem:
    """Return the process-wide JobStore + JobWorker bundle, creating
    it lazily on first call. Safe to call from any thread.
    """
    global _singleton
    with _lock:
        if _singleton is not None:
            return _singleton
        db_path = _resolve_db_path(config)
        store = JobStore(db_path)
        recovered = store.recover_orphaned()
        if recovered.total:
            _LOG.warning(
                "delegate-job subsystem: orphan recovery — re-queued %d "
                "read-only job(s), failed %d (server_restart)",
                recovered.requeued, recovered.failed,
            )
        # v26.0.0 — orphan sweep for instruction-mode rows whose caller
        # never invoked record_delegation_result. Runs once at boot;
        # record_delegation_result also calls this opportunistically so
        # we don't need a separate heartbeat thread. Operators who want
        # to keep stale rows around set awaiting_caller_timeout_seconds=0.
        ttl = config.delegate.awaiting_caller_timeout_seconds
        if ttl > 0:
            swept = store.sweep_stale_awaiting_caller(max_age_seconds=ttl)
            if swept:
                _LOG.info(
                    "delegate-job subsystem: swept %d stale awaiting_caller "
                    "rows (ttl=%ds)", swept, ttl,
                )
        # v23.0.0a2: prune old rows so unbounded growth doesn't
        # accumulate across process lifetimes. Runs ONCE per boot —
        # not on every enqueue. Default retain=1000 (overridable via
        # [delegate] retain_recent_k).
        pruned = store.prune_old(retain=config.delegate.retain_recent_k)
        if pruned:
            _LOG.info(
                "delegate-job subsystem: pruned %d old rows "
                "(retain=%d)", pruned, config.delegate.retain_recent_k,
            )
        # v24.0.0a1: spawn N workers per [delegate] worker_count.
        # All share the same JobStore — the atomic UPDATE ... RETURNING
        # claim_next_queued ensures no double-processing across
        # workers. Default worker_count=1 preserves v22/v23 behaviour.
        n = config.delegate.worker_count
        workers = [JobWorker(config=config, store=store) for _ in range(n)]
        for w in workers:
            w.start()
        broadcaster = JobEventBroadcaster()
        # v22.2.0: bridge JobStore's sync subscriber hook to the
        # broadcaster's threadsafe publish so SSE consumers (and any
        # future push transport) receive every completion / failure.
        store.add_subscriber(broadcaster.publish_threadsafe)

        # v24.0.0a7: opt-in FleetQ Bridge completion publisher.
        # Three-gate check (publish_completions + team_id + token)
        # lives inside the publisher; subsystem just wires the
        # callback if the [fleetq] extra is importable. When the
        # extra isn't installed, the import fails and we skip
        # silently — same shape as other [fleetq] hooks.
        try:
            from harbormaster.fleetq.completions import CompletionPublisher
            publisher = CompletionPublisher(config)
            if publisher.is_armed():
                store.add_subscriber(publisher.publish)
                _LOG.info(
                    "delegate-job subsystem: fleetq completion "
                    "publisher armed (team_id=%s, endpoint=%s)",
                    config.fleetq.team_id,
                    config.fleetq.base_url.rstrip("/")
                    + "/api/v1/harbormaster/job-completed",
                )
        except ImportError:
            pass
        _singleton = Subsystem(
            store=store, workers=workers, broadcaster=broadcaster,
        )
        _LOG.info(
            "delegate-job subsystem ready at %s (workers=%d)", db_path, n,
        )
        return _singleton


def shutdown_subsystem() -> None:
    """Tear down the singleton — mainly for tests so each test starts
    from a clean slate."""
    global _singleton
    with _lock:
        if _singleton is None:
            return
        _singleton.shutdown()
        _singleton = None

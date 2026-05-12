"""Thread-safe → asyncio bridge for JobStore state changes (v22.2.0).

The JobWorker runs on a daemon thread and fires ``_fire_completion``
from there. Asyncio queues are not thread-safe, so we need a small
broadcaster that captures the event-loop reference at subscribe time
and dispatches via ``loop.call_soon_threadsafe`` from the worker
thread.

Pattern mirrors ``harbormaster.ui.network_log.network_log`` for new
MCPCallLog events — pubsub from sync producer to async SSE consumer.
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
import threading
from typing import Any

from harbormaster.jobs.store import Job

_LOG = logging.getLogger(__name__)


class JobEventBroadcaster:
    """Pubsub for ``Job`` state changes; threadsafe producer side."""

    def __init__(self) -> None:
        self._subscribers: list[
            tuple[asyncio.Queue[dict[str, Any]], asyncio.AbstractEventLoop]
        ] = []
        self._lock = threading.Lock()

    def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        """Register a new subscriber; called from an asyncio coroutine
        so the running loop reference is captured for cross-thread
        dispatch."""
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        with self._lock:
            self._subscribers.append((queue, loop))
        return queue

    def unsubscribe(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        with self._lock:
            self._subscribers = [
                (q, loop) for (q, loop) in self._subscribers if q is not queue
            ]

    def publish_threadsafe(self, job: Job) -> None:
        """Producer side. Called from any thread (typically the
        JobWorker). Loop-closed subscribers are silently pruned —
        a closed loop means the SSE consumer already disconnected.
        """
        payload = job.as_dict()
        with self._lock:
            subs = list(self._subscribers)
        for queue, loop in subs:
            with contextlib.suppress(RuntimeError):
                loop.call_soon_threadsafe(queue.put_nowait, payload)

    def subscriber_count(self) -> int:
        with self._lock:
            return len(self._subscribers)

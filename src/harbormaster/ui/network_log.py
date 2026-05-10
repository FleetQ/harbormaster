"""v10.0.0a7: in-process ring buffer of MCP-call events.

Powers `/network` (graph view) and `/network/chat` (chronological
log) by recording every MCP tool dispatch the UI sees. Ring buffer
size = 500 events; older entries are evicted FIFO.

The buffer is per-process — it does NOT persist to sqlite or stream
to FleetQ Memory (Phase 7 does the in-memory ring; persistence is
a v11 candidate). SSE subscribers get a `notify_event` push as new
records land so the UI doesn't need to poll.
"""
from __future__ import annotations

import asyncio
import contextlib
import time
from collections import deque
from dataclasses import asdict, dataclass
from typing import Literal

# Allowed tool names. Keep this in sync with what
# `harbormaster.tools.dispatcher.SAFE_FOR_PARALLEL` exposes — the v7
# audit confirmed these are the user-visible MCP entry points that
# carry an inter-project semantic (caller-project → target-project).
NetworkTool = Literal[
    "ask_project",
    "delegate_task",
    "fan_out_ask",
    "recall_qa",
]

NetworkStatus = Literal["start", "ok", "error"]

# Cap chosen to bound memory cost (~500 * ~400B = 200KB) while still
# covering an active operator's last hour of activity.
_MAX_EVENTS: int = 500


@dataclass(frozen=True)
class NetworkEvent:
    """One MCP-tool dispatch recorded for the network view.

    `caller` is the source project name OR the literal "operator"
    when the call originated from the UI directly (no parent project
    context). `target` is the project the tool was asked about; for
    `fan_out_ask` the recorder writes one event per target so each
    fan-out leg is a distinct edge in the graph.
    """

    timestamp_ms: int  # epoch milliseconds for client-side sort
    caller: str
    target: str
    tool: str
    status: str
    question_preview: str  # first 200 chars; never the full prompt

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


class _MCPCallLog:
    """Async-friendly ring buffer + fan-out for SSE subscribers.

    Thread-safety: `record()` uses a normal `deque` (atomic append in
    CPython under the GIL). `subscribe()` returns an `asyncio.Queue`
    that the caller awaits; `_notify()` puts to every active queue.
    """

    def __init__(self, max_events: int = _MAX_EVENTS) -> None:
        self._events: deque[NetworkEvent] = deque(maxlen=max_events)
        self._subscribers: list[asyncio.Queue[NetworkEvent]] = []

    def record(
        self,
        *,
        caller: str,
        target: str,
        tool: str,
        status: str = "ok",
        question_preview: str = "",
    ) -> NetworkEvent:
        ev = NetworkEvent(
            timestamp_ms=int(time.time() * 1000),
            caller=caller or "operator",
            target=target,
            tool=tool,
            status=status,
            question_preview=question_preview[:200],
        )
        self._events.append(ev)
        self._notify(ev)
        return ev

    def recent(self, limit: int | None = None) -> list[NetworkEvent]:
        if limit is None or limit >= len(self._events):
            return list(self._events)
        # `deque` slicing isn't supported; convert then slice for the
        # last N entries.
        return list(self._events)[-limit:]

    def subscribe(self) -> asyncio.Queue[NetworkEvent]:
        """Return a queue that yields every NEW event recorded after
        the call. Caller is responsible for `unsubscribe()` on exit
        so we don't leak per-connection queues."""
        q: asyncio.Queue[NetworkEvent] = asyncio.Queue(maxsize=128)
        self._subscribers.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue[NetworkEvent]) -> None:
        with contextlib.suppress(ValueError):
            self._subscribers.remove(q)

    def _notify(self, ev: NetworkEvent) -> None:
        # Non-blocking put; if a subscriber's queue is full (slow
        # consumer) we drop the event for them — the ring buffer
        # still has the canonical record for `recent()` polling.
        for q in self._subscribers:
            with contextlib.suppress(asyncio.QueueFull):
                q.put_nowait(ev)

    def clear(self) -> None:
        """Used by tests to reset between cases."""
        self._events.clear()


# Module-level singleton. The UI app reaches for this directly so the
# instrumentation hook in `_stream_local_tool` / `_stream_remote_tool`
# can `from harbormaster.ui.network_log import network_log` without
# threading the instance through every call site.
network_log = _MCPCallLog()

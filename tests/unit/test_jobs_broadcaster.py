"""Unit tests for ``JobEventBroadcaster`` (v22.2.0).

Validates the threadsafe → asyncio bridge: worker-thread
``publish_threadsafe`` calls land in subscriber asyncio queues
without race or loss.
"""
from __future__ import annotations

import asyncio
import threading

import pytest

from harbormaster.jobs.broadcaster import JobEventBroadcaster
from harbormaster.jobs.store import Job

# We can't construct a full Job easily; just use minimal field set.
_DUMMY_JOB = Job(
    id="d_test01", inbox_id="inbox-x", project="alpha", host=None,
    task="t", deliverable="d", allow_writes=False, model=None,
    status="completed", output="ok", error=None, cid=None,
    queued_at=1.0, started_at=2.0, completed_at=3.0,
    duration_ms=1000, read_at=None, max_turns=10,
)


@pytest.mark.asyncio
async def test_publish_lands_in_subscriber_queue():
    b = JobEventBroadcaster()
    q = b.subscribe()
    b.publish_threadsafe(_DUMMY_JOB)
    ev = await asyncio.wait_for(q.get(), timeout=1.0)
    assert ev["job_id"] == "d_test01"
    assert ev["status"] == "completed"


@pytest.mark.asyncio
async def test_multiple_subscribers_each_receive():
    b = JobEventBroadcaster()
    q1 = b.subscribe()
    q2 = b.subscribe()
    b.publish_threadsafe(_DUMMY_JOB)
    ev1 = await asyncio.wait_for(q1.get(), timeout=1.0)
    ev2 = await asyncio.wait_for(q2.get(), timeout=1.0)
    assert ev1["job_id"] == "d_test01"
    assert ev2["job_id"] == "d_test01"


@pytest.mark.asyncio
async def test_unsubscribe_stops_receiving():
    b = JobEventBroadcaster()
    q = b.subscribe()
    b.unsubscribe(q)
    b.publish_threadsafe(_DUMMY_JOB)
    # Queue should be empty after a short wait.
    with pytest.raises(TimeoutError):
        await asyncio.wait_for(q.get(), timeout=0.2)


@pytest.mark.asyncio
async def test_publish_from_worker_thread_safe():
    """The producer side runs on the JobWorker thread in production;
    explicitly exercise that path with a real threading.Thread."""
    b = JobEventBroadcaster()
    q = b.subscribe()

    def producer() -> None:
        b.publish_threadsafe(_DUMMY_JOB)

    t = threading.Thread(target=producer)
    t.start()
    ev = await asyncio.wait_for(q.get(), timeout=1.0)
    t.join()
    assert ev["job_id"] == "d_test01"


def test_subscriber_count_tracks_lifecycle():
    b = JobEventBroadcaster()
    assert b.subscriber_count() == 0
    # Subscribe needs a running loop, so wrap in asyncio.run.
    queues: list[asyncio.Queue] = []  # type: ignore[type-arg]

    async def _add():
        queues.append(b.subscribe())
        queues.append(b.subscribe())
        return b.subscriber_count()

    count = asyncio.run(_add())
    # Both subscribers got created with their own loops; count includes
    # any whose loop is still alive at lookup time. After asyncio.run
    # returns, the loops are closed; publish_threadsafe will swallow
    # them.
    assert count == 2

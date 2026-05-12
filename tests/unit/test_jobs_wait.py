"""Unit tests for the v22.1.0 blocking-wait primitives on JobStore.

Covers the threading.Event + threading.Condition wakeup paths in
isolation — no MCP tool layer, no fake_claude. The fan_out-style
integration sits in ``tests/integration/test_jobs_await_e2e.py``.
"""
from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

from harbormaster.jobs.schema import STATUS_COMPLETED, STATUS_FAILED
from harbormaster.jobs.store import JobStore


@pytest.fixture
def store(tmp_path: Path) -> JobStore:
    return JobStore(tmp_path / "jobs.db")


def test_wait_for_job_returns_immediately_when_already_completed(store: JobStore):
    job = store.enqueue(
        project="alpha", host=None, task="t", deliverable="d",
        allow_writes=False, model=None,
    )
    store.claim_next_queued()
    store.complete(job.id, output="done", duration_ms=5)

    start = time.monotonic()
    result = store.wait_for_job(job.id, timeout_seconds=10.0)
    elapsed = time.monotonic() - start

    assert result is not None
    assert result.status == STATUS_COMPLETED
    assert result.output == "done"
    # Fast-path check: must NOT block for the full timeout.
    assert elapsed < 0.5


def test_wait_for_job_returns_none_for_unknown_id(store: JobStore):
    result = store.wait_for_job("d_nope", timeout_seconds=0.1)
    assert result is None


def test_wait_for_job_wakes_on_completion(store: JobStore):
    job = store.enqueue(
        project="alpha", host=None, task="t", deliverable="d",
        allow_writes=False, model=None,
    )
    # Park a waiter on the job. Use a thread so we can complete from
    # the main thread mid-wait.
    result_holder: dict[str, object] = {}

    def waiter() -> None:
        result_holder["job"] = store.wait_for_job(
            job.id, timeout_seconds=5.0,
        )
        result_holder["elapsed"] = time.monotonic()

    waiter_start = time.monotonic()
    t = threading.Thread(target=waiter)
    t.start()
    # Give the waiter time to actually enter ev.wait().
    time.sleep(0.1)
    store.claim_next_queued()
    store.complete(job.id, output="from-other-thread", duration_ms=1)

    t.join(timeout=2.0)
    assert not t.is_alive(), "waiter did not wake up after complete()"
    result = result_holder["job"]
    assert result is not None and result.status == STATUS_COMPLETED  # type: ignore[union-attr]
    # Confirm we did NOT burn the full timeout.
    elapsed = float(result_holder["elapsed"]) - waiter_start  # type: ignore[arg-type]
    assert elapsed < 2.0


def test_wait_for_job_wakes_on_failure(store: JobStore):
    job = store.enqueue(
        project="alpha", host=None, task="t", deliverable="d",
        allow_writes=False, model=None,
    )
    result_holder: dict[str, object] = {}

    def waiter() -> None:
        result_holder["job"] = store.wait_for_job(
            job.id, timeout_seconds=5.0,
        )

    t = threading.Thread(target=waiter)
    t.start()
    time.sleep(0.1)
    store.claim_next_queued()
    store.fail(
        job.id, error="Error: ... [cid=ff00] — code=x: y",
        cid="ff00", duration_ms=1,
    )

    t.join(timeout=2.0)
    assert not t.is_alive()
    result = result_holder["job"]
    assert result is not None and result.status == STATUS_FAILED  # type: ignore[union-attr]


def test_wait_for_job_returns_running_on_timeout(store: JobStore):
    job = store.enqueue(
        project="alpha", host=None, task="t", deliverable="d",
        allow_writes=False, model=None,
    )
    # Don't complete it — let wait time out.
    result = store.wait_for_job(job.id, timeout_seconds=0.2)
    assert result is not None
    # Status is "queued" because nobody claimed it.
    assert result.status == "queued"


def test_wait_for_inbox_returns_existing_pending_immediately(store: JobStore):
    job = store.enqueue(
        project="alpha", host=None, task="t", deliverable="d",
        allow_writes=False, model=None, inbox_id="i1",
    )
    store.claim_next_queued()
    store.complete(job.id, output="ok", duration_ms=1)

    start = time.monotonic()
    out = store.wait_for_inbox("i1", timeout_seconds=10.0)
    elapsed = time.monotonic() - start

    assert [j.id for j in out] == [job.id]
    assert elapsed < 0.5


def test_wait_for_inbox_wakes_on_any_completion(store: JobStore):
    job_a = store.enqueue(
        project="alpha", host=None, task="t", deliverable="d",
        allow_writes=False, model=None, inbox_id="batch",
    )
    job_b = store.enqueue(
        project="beta", host=None, task="t", deliverable="d",
        allow_writes=False, model=None, inbox_id="batch",
    )

    result_holder: dict[str, list[str]] = {}

    def waiter() -> None:
        result_holder["ids"] = [
            j.id for j in store.wait_for_inbox(
                "batch", timeout_seconds=5.0,
            )
        ]

    t = threading.Thread(target=waiter)
    t.start()
    time.sleep(0.1)
    # Complete only job_a — waiter should wake with [a], not block
    # for job_b too.
    store.claim_next_queued()
    store.complete(job_a.id, output="a-done", duration_ms=1)

    t.join(timeout=2.0)
    assert not t.is_alive()
    assert result_holder["ids"] == [job_a.id]
    # job_b is still queued, untouched.
    job_b_after = store.get(job_b.id)
    assert job_b_after is not None and job_b_after.status == "queued"


def test_wait_for_inbox_returns_empty_on_timeout(store: JobStore):
    out = store.wait_for_inbox("empty-inbox", timeout_seconds=0.2)
    assert out == []


def test_wait_for_inbox_filters_by_since(store: JobStore):
    """``since`` skips completions the caller has already drained."""
    job_a = store.enqueue(
        project="alpha", host=None, task="t", deliverable="d",
        allow_writes=False, model=None, inbox_id="filt",
    )
    store.claim_next_queued()
    store.complete(job_a.id, output="a", duration_ms=1)
    job_a_state = store.get(job_a.id)
    assert job_a_state is not None and job_a_state.completed_at is not None

    # Caller saw job_a; wait for the NEXT completion only.
    job_b = store.enqueue(
        project="beta", host=None, task="t", deliverable="d",
        allow_writes=False, model=None, inbox_id="filt",
    )
    result_holder: dict[str, list[str]] = {}

    def waiter() -> None:
        result_holder["ids"] = [
            j.id for j in store.wait_for_inbox(
                "filt",
                timeout_seconds=5.0,
                since=job_a_state.completed_at,
            )
        ]

    t = threading.Thread(target=waiter)
    t.start()
    time.sleep(0.1)
    store.claim_next_queued()
    store.complete(job_b.id, output="b", duration_ms=1)

    t.join(timeout=2.0)
    assert not t.is_alive()
    # Only job_b — job_a's earlier completion is filtered by ``since``.
    assert result_holder["ids"] == [job_b.id]


def test_subscriber_callback_fires_on_completion(store: JobStore):
    """v22.2.0 hook: registered callbacks see the final ``Job``."""
    seen: list[tuple[str, str]] = []

    def sub(job):  # type: ignore[no-untyped-def]
        seen.append((job.id, job.status))

    store.add_subscriber(sub)
    job = store.enqueue(
        project="alpha", host=None, task="t", deliverable="d",
        allow_writes=False, model=None,
    )
    store.claim_next_queued()
    store.complete(job.id, output="ok", duration_ms=1)

    # Allow time for the synchronous callback to run.
    assert seen == [(job.id, STATUS_COMPLETED)]
    store.remove_subscriber(sub)


def test_subscriber_callback_exception_does_not_break_completion(store: JobStore):
    """Subscriber exceptions are swallowed — broken subscribers must
    not corrupt JobStore state for other waiters."""
    def boom(_job):  # type: ignore[no-untyped-def]
        raise RuntimeError("subscriber crash")

    store.add_subscriber(boom)
    job = store.enqueue(
        project="alpha", host=None, task="t", deliverable="d",
        allow_writes=False, model=None,
    )
    store.claim_next_queued()
    # Must not raise.
    store.complete(job.id, output="ok", duration_ms=1)
    final = store.get(job.id)
    assert final is not None and final.status == STATUS_COMPLETED

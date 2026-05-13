"""Unit tests for the v25.0.0 agent clarification primitives on JobStore."""
from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

from harbormaster.jobs.schema import STATUS_CLR_ANSWERED, STATUS_CLR_PENDING
from harbormaster.jobs.store import JobStore


@pytest.fixture
def store(tmp_path: Path) -> JobStore:
    return JobStore(tmp_path / "jobs.db")


def _enqueue_and_claim(store: JobStore) -> str:
    job = store.enqueue(
        project="alpha", host=None, task="t", deliverable="d",
        allow_writes=False, model=None,
    )
    store.claim_next_queued()
    return job.id


# ---------------------------------------------------------------------------
# add / answer / get
# ---------------------------------------------------------------------------

def test_add_clarification_creates_pending_row(store: JobStore) -> None:
    job_id = _enqueue_and_claim(store)
    clr_id = store.add_clarification(job_id, "What format?")
    assert clr_id.startswith("clr_")
    pending = store.get_pending_clarifications(job_id)
    assert len(pending) == 1
    assert pending[0].id == clr_id
    assert pending[0].status == STATUS_CLR_PENDING
    assert pending[0].question == "What format?"
    assert pending[0].answer is None


def test_answer_clarification_marks_answered(store: JobStore) -> None:
    job_id = _enqueue_and_claim(store)
    clr_id = store.add_clarification(job_id, "Output type?")

    ok = store.answer_clarification(clr_id, "JSON")
    assert ok is True

    clr = store.get_clarification(clr_id)
    assert clr is not None
    assert clr.status == STATUS_CLR_ANSWERED
    assert clr.answer == "JSON"
    assert clr.answered_at is not None


def test_answer_clarification_returns_false_when_already_answered(store: JobStore) -> None:
    job_id = _enqueue_and_claim(store)
    clr_id = store.add_clarification(job_id, "Q")
    assert store.answer_clarification(clr_id, "A") is True
    assert store.answer_clarification(clr_id, "A again") is False


def test_answer_clarification_returns_false_for_unknown_id(store: JobStore) -> None:
    assert store.answer_clarification("clr_nope", "A") is False


def test_get_pending_clarifications_excludes_answered(store: JobStore) -> None:
    job_id = _enqueue_and_claim(store)
    clr_a = store.add_clarification(job_id, "Q1")
    clr_b = store.add_clarification(job_id, "Q2")
    store.answer_clarification(clr_a, "A1")
    pending = store.get_pending_clarifications(job_id)
    assert [c.id for c in pending] == [clr_b]


def test_get_clarification_returns_none_for_unknown(store: JobStore) -> None:
    assert store.get_clarification("clr_missing") is None


# ---------------------------------------------------------------------------
# wait_for_clarification_answer — blocking
# ---------------------------------------------------------------------------

def test_wait_for_clarification_answer_returns_immediately_if_already_answered(
    store: JobStore,
) -> None:
    job_id = _enqueue_and_claim(store)
    clr_id = store.add_clarification(job_id, "Q?")
    store.answer_clarification(clr_id, "A!")

    start = time.monotonic()
    result = store.wait_for_clarification_answer(clr_id, timeout_seconds=10.0)
    assert time.monotonic() - start < 0.5
    assert result is not None
    assert result.status == STATUS_CLR_ANSWERED
    assert result.answer == "A!"


def test_wait_for_clarification_answer_returns_none_for_unknown(store: JobStore) -> None:
    result = store.wait_for_clarification_answer("clr_nope", timeout_seconds=0.1)
    assert result is None


def test_wait_for_clarification_answer_wakes_on_answer(store: JobStore) -> None:
    job_id = _enqueue_and_claim(store)
    clr_id = store.add_clarification(job_id, "Q?")

    result_holder: dict[str, object] = {}

    def waiter() -> None:
        result_holder["clr"] = store.wait_for_clarification_answer(
            clr_id, timeout_seconds=5.0,
        )
        result_holder["elapsed"] = time.monotonic()

    t_start = time.monotonic()
    t = threading.Thread(target=waiter)
    t.start()
    time.sleep(0.1)
    store.answer_clarification(clr_id, "The answer")

    t.join(timeout=2.0)
    assert not t.is_alive(), "waiter did not wake on answer"
    clr = result_holder["clr"]
    assert clr is not None
    assert clr.status == STATUS_CLR_ANSWERED  # type: ignore[union-attr]
    assert clr.answer == "The answer"  # type: ignore[union-attr]
    assert float(result_holder["elapsed"]) - t_start < 2.0  # type: ignore[arg-type]


def test_wait_for_clarification_answer_returns_on_timeout(store: JobStore) -> None:
    job_id = _enqueue_and_claim(store)
    clr_id = store.add_clarification(job_id, "Q?")

    result = store.wait_for_clarification_answer(clr_id, timeout_seconds=0.2)
    assert result is not None
    assert result.status == STATUS_CLR_PENDING


# ---------------------------------------------------------------------------
# wait_for_clarification_request — blocking
# ---------------------------------------------------------------------------

def test_wait_for_clarification_request_returns_existing_immediately(
    store: JobStore,
) -> None:
    job_id = _enqueue_and_claim(store)
    store.add_clarification(job_id, "Already pending Q")

    start = time.monotonic()
    pending = store.wait_for_clarification_request(job_id, timeout_seconds=10.0)
    assert time.monotonic() - start < 0.5
    assert len(pending) == 1
    assert pending[0].question == "Already pending Q"


def test_wait_for_clarification_request_wakes_on_new_question(store: JobStore) -> None:
    job_id = _enqueue_and_claim(store)
    result_holder: dict[str, object] = {}

    def orchestrator() -> None:
        result_holder["pending"] = store.wait_for_clarification_request(
            job_id, timeout_seconds=5.0,
        )
        result_holder["elapsed"] = time.monotonic()

    t_start = time.monotonic()
    t = threading.Thread(target=orchestrator)
    t.start()
    time.sleep(0.1)
    store.add_clarification(job_id, "New question from subagent")

    t.join(timeout=2.0)
    assert not t.is_alive(), "orchestrator did not wake on new clarification"
    pending = result_holder["pending"]
    assert isinstance(pending, list) and len(pending) == 1
    assert pending[0].question == "New question from subagent"  # type: ignore[union-attr]
    assert float(result_holder["elapsed"]) - t_start < 2.0  # type: ignore[arg-type]


def test_wait_for_clarification_request_returns_empty_on_timeout(store: JobStore) -> None:
    job_id = _enqueue_and_claim(store)
    pending = store.wait_for_clarification_request(job_id, timeout_seconds=0.2)
    assert pending == []


def test_wait_for_clarification_request_wakes_on_job_completion(store: JobStore) -> None:
    """_fire_completion notifies job clarification conditions so the orchestrator
    doesn't hang if the subagent finishes without ever asking anything."""
    job_id = _enqueue_and_claim(store)
    result_holder: dict[str, object] = {}

    def orchestrator() -> None:
        result_holder["pending"] = store.wait_for_clarification_request(
            job_id, timeout_seconds=5.0,
        )

    t = threading.Thread(target=orchestrator)
    t.start()
    time.sleep(0.1)
    store.complete(job_id, output="done", duration_ms=1)

    t.join(timeout=2.0)
    assert not t.is_alive(), "orchestrator did not wake on job completion"
    # No pending clarifications — job finished cleanly.
    assert result_holder["pending"] == []


# ---------------------------------------------------------------------------
# as_dict
# ---------------------------------------------------------------------------

def test_clarification_as_dict_shape(store: JobStore) -> None:
    job_id = _enqueue_and_claim(store)
    clr_id = store.add_clarification(job_id, "Q?")
    store.answer_clarification(clr_id, "A!")
    clr = store.get_clarification(clr_id)
    assert clr is not None
    d = clr.as_dict()
    assert d["clarification_id"] == clr_id
    assert d["job_id"] == job_id
    assert d["question"] == "Q?"
    assert d["answer"] == "A!"
    assert d["status"] == STATUS_CLR_ANSWERED
    assert d["asked_at"] is not None
    assert d["answered_at"] is not None

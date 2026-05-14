"""End-to-end test for the v22.1.0 blocking-await MCP tools.

Exercises ``await_delegated_task`` and ``await_inbox`` through the
real ``delegate_task(mode="async")`` worker pipeline with fake_claude.
"""
from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

from harbormaster.config import (
    BackendConfig,
    DelegateConfig,
    HarbormasterConfig,
    ProjectsConfig,
)
from harbormaster.jobs.subsystem import shutdown_subsystem
from harbormaster.server import build_server

FAKE_CLAUDE = Path(__file__).resolve().parent.parent / "fixtures" / "fake_claude.py"


@pytest.fixture
def fake_config(tmp_path: Path, monkeypatch) -> HarbormasterConfig:
    code = tmp_path / "code"
    for name in ("alpha", "beta", "gamma"):
        (code / name).mkdir(parents=True)
        (code / name / "CLAUDE.md").write_text(f"# {name}", encoding="utf-8")
    monkeypatch.setenv("HARBORMASTER_JOBS_DB", str(tmp_path / "jobs.db"))
    return HarbormasterConfig(
        projects=ProjectsConfig(glob=[f"{tmp_path}/code/*"]),
        backends={
            "claude": BackendConfig(
                binary=str(FAKE_CLAUDE), timeout_local=10,
            ),
        },
        # v26.0.0 — pin to subprocess so the fake_claude binary runs.
        delegate=DelegateConfig(execution_mode="subprocess"),
    )


@pytest.fixture(autouse=True)
def _isolate_subsystem():
    yield
    shutdown_subsystem()


def _tools(mcp):
    return {t.name: t for t in mcp._tool_manager.list_tools()}


def _job_id_from_handle(handle: str) -> str:
    return handle.split(" ", 2)[1]


def test_await_delegated_task_unblocks_on_worker_completion(
    fake_config: HarbormasterConfig,
):
    mcp = build_server(fake_config)
    tools = _tools(mcp)
    delegate = tools["delegate_task"].fn
    awaiter = tools["await_delegated_task"].fn

    handle = delegate(
        name="alpha", task="t", deliverable="d",
        allow_writes=False, mode="async",
    )
    job_id = _job_id_from_handle(handle)

    start = time.monotonic()
    result = awaiter(job_id=job_id, timeout_seconds=10.0)
    elapsed = time.monotonic() - start

    assert result["status"] == "completed"
    assert "FAKE_CLAUDE answered" in (result["output"] or "")
    # fake_claude is essentially instant; the awaiter must NOT have
    # consumed anything close to the full timeout.
    assert elapsed < 5.0


def test_await_delegated_task_times_out_with_running_status(
    fake_config: HarbormasterConfig, monkeypatch,
):
    """When the worker is slow, the awaiter times out and the caller
    sees ``status="running"`` (or ``"queued"``), not an exception."""
    monkeypatch.setenv("HARBORMASTER_FAKE_CLAUDE_FAIL", "timeout")

    mcp = build_server(fake_config)
    tools = _tools(mcp)
    delegate = tools["delegate_task"].fn
    awaiter = tools["await_delegated_task"].fn

    handle = delegate(
        name="alpha", task="t", deliverable="d",
        allow_writes=False, mode="async",
    )
    job_id = _job_id_from_handle(handle)

    result = awaiter(job_id=job_id, timeout_seconds=0.5)
    assert result["status"] in ("queued", "running")
    assert result["job_id"] == job_id


def test_await_delegated_task_returns_not_found_for_unknown(
    fake_config: HarbormasterConfig,
):
    mcp = build_server(fake_config)
    awaiter = _tools(mcp)["await_delegated_task"].fn
    out = awaiter(job_id="d_bogus123", timeout_seconds=0.1)
    assert out == {"error": "not_found", "job_id": "d_bogus123"}


def test_await_inbox_fires_on_first_completion(fake_config: HarbormasterConfig):
    """Fan-out of 3 jobs to one inbox; ``await_inbox`` must wake on the
    first completion, not block for all three."""
    mcp = build_server(fake_config)
    tools = _tools(mcp)
    delegate = tools["delegate_task"].fn
    inbox_wait = tools["await_inbox"].fn
    get_status = tools["get_delegated_task"].fn

    handles = [
        delegate(
            name=p, task="t", deliverable="d",
            allow_writes=False, mode="async", inbox_id="batch",
        )
        for p in ("alpha", "beta", "gamma")
    ]
    job_ids = [_job_id_from_handle(h) for h in handles]

    first = inbox_wait(inbox_id="batch", timeout_seconds=10.0)
    assert not first["timed_out"]
    assert len(first["results"]) >= 1
    assert first["results"][0]["job_id"] in job_ids

    # Drain the rest (cleanup).
    end = time.monotonic() + 5.0
    while time.monotonic() < end:
        if all(
            get_status(job_id=jid).get("status") == "completed"
            for jid in job_ids
        ):
            break
        time.sleep(0.05)


def test_await_inbox_times_out_cleanly(fake_config: HarbormasterConfig):
    mcp = build_server(fake_config)
    inbox_wait = _tools(mcp)["await_inbox"].fn
    start = time.monotonic()
    out = inbox_wait(inbox_id="no-jobs-here", timeout_seconds=0.3)
    elapsed = time.monotonic() - start
    assert out == {
        "inbox_id": "no-jobs-here", "results": [], "timed_out": True,
    }
    assert 0.25 < elapsed < 1.0


def test_await_inbox_concurrent_threads_each_wake(fake_config: HarbormasterConfig):
    """Two concurrent inbox waiters both wake on the same completion —
    Condition.notify_all() not notify(). Regression guard."""
    mcp = build_server(fake_config)
    tools = _tools(mcp)
    delegate = tools["delegate_task"].fn
    inbox_wait = tools["await_inbox"].fn

    results: list[dict[str, object] | None] = [None, None]

    def waiter(i: int) -> None:
        results[i] = inbox_wait(
            inbox_id="concurrent-batch", timeout_seconds=5.0,
        )

    threads = [threading.Thread(target=waiter, args=(i,)) for i in range(2)]
    for t in threads:
        t.start()
    time.sleep(0.1)  # let both enter the wait
    delegate(
        name="alpha", task="t", deliverable="d",
        allow_writes=False, mode="async", inbox_id="concurrent-batch",
    )
    for t in threads:
        t.join(timeout=3.0)
        assert not t.is_alive()

    for r in results:
        assert isinstance(r, dict)
        assert r["timed_out"] is False
        assert len(r["results"]) == 1  # type: ignore[arg-type]

"""End-to-end test for the inbox half of the async delegate flow
(v22.0.0a3).

Exercises ``recall_pending_results`` against a JobStore populated by
real ``delegate_task(..., mode="async")`` calls and the fake_claude
worker. Verifies FIFO order, mark_read consumption, peek behaviour
(``mark_read=False``), and per-inbox isolation.
"""
from __future__ import annotations

import time
from pathlib import Path

import pytest

from harbormaster.config import BackendConfig, HarbormasterConfig, ProjectsConfig
from harbormaster.jobs.subsystem import shutdown_subsystem
from harbormaster.server import build_server

FAKE_CLAUDE = Path(__file__).resolve().parent.parent / "fixtures" / "fake_claude.py"


@pytest.fixture
def fake_config(tmp_path: Path, monkeypatch) -> HarbormasterConfig:
    code = tmp_path / "code"
    for name in ("alpha", "beta"):
        (code / name).mkdir(parents=True)
        (code / name / "CLAUDE.md").write_text(f"# {name}", encoding="utf-8")
    monkeypatch.setenv("HARBORMASTER_JOBS_DB", str(tmp_path / "jobs.db"))
    return HarbormasterConfig(
        projects=ProjectsConfig(glob=[f"{tmp_path}/code/*"]),
        backends={"claude": BackendConfig(binary=str(FAKE_CLAUDE), timeout_local=10)},
    )


@pytest.fixture(autouse=True)
def _isolate_subsystem():
    yield
    shutdown_subsystem()


def _tools(mcp):
    return {t.name: t for t in mcp._tool_manager.list_tools()}


def _wait_until(predicate, timeout: float = 5.0, poll: float = 0.05) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate():
            return True
        time.sleep(poll)
    return False


def test_inbox_drains_in_fifo_order_and_marks_read(fake_config: HarbormasterConfig):
    mcp = build_server(fake_config)
    tools = _tools(mcp)
    delegate = tools["delegate_task"].fn
    recall = tools["recall_pending_results"].fn

    handles = [
        delegate(
            name=name, task="t", deliverable="d",
            allow_writes=False, mode="async", inbox_id="sprint-X",
        )
        for name in ("alpha", "beta", "alpha")
    ]
    job_ids = [h.split(" ", 2)[1] for h in handles]

    # Wait for all 3 to complete.
    get_status = tools["get_delegated_task"].fn
    assert _wait_until(
        lambda: all(
            get_status(job_id=jid).get("status") == "completed"
            for jid in job_ids
        ),
        timeout=8.0,
    )

    # First poll: returns all 3 + marks them read.
    out = recall(inbox_id="sprint-X")
    assert out["inbox_id"] == "sprint-X"
    assert [r["job_id"] for r in out["results"]] == job_ids
    assert out["marked_read"] == 3

    # Second poll: empty (everything was consumed).
    out2 = recall(inbox_id="sprint-X")
    assert out2["results"] == []
    assert out2["marked_read"] == 0


def test_inbox_peek_does_not_consume(fake_config: HarbormasterConfig):
    mcp = build_server(fake_config)
    tools = _tools(mcp)
    delegate = tools["delegate_task"].fn
    recall = tools["recall_pending_results"].fn
    get_status = tools["get_delegated_task"].fn

    handle = delegate(
        name="alpha", task="t", deliverable="d",
        allow_writes=False, mode="async", inbox_id="peek-test",
    )
    job_id = handle.split(" ", 2)[1]
    assert _wait_until(
        lambda: get_status(job_id=job_id).get("status") == "completed",
    )

    # Peek twice — both polls see the same row, neither consumes it.
    peek1 = recall(inbox_id="peek-test", mark_read=False)
    peek2 = recall(inbox_id="peek-test", mark_read=False)
    assert len(peek1["results"]) == 1
    assert len(peek2["results"]) == 1
    assert peek1["marked_read"] == 0
    assert peek2["marked_read"] == 0
    assert peek1["results"][0]["job_id"] == job_id

    # Real poll consumes.
    drained = recall(inbox_id="peek-test")
    assert drained["marked_read"] == 1
    # After drain: nothing left.
    assert recall(inbox_id="peek-test")["results"] == []


def test_inbox_isolation_between_inbox_ids(fake_config: HarbormasterConfig):
    mcp = build_server(fake_config)
    tools = _tools(mcp)
    delegate = tools["delegate_task"].fn
    recall = tools["recall_pending_results"].fn
    get_status = tools["get_delegated_task"].fn

    handle_a = delegate(
        name="alpha", task="t", deliverable="d",
        allow_writes=False, mode="async", inbox_id="inbox-A",
    )
    handle_b = delegate(
        name="beta", task="t", deliverable="d",
        allow_writes=False, mode="async", inbox_id="inbox-B",
    )
    job_a = handle_a.split(" ", 2)[1]
    job_b = handle_b.split(" ", 2)[1]

    assert _wait_until(
        lambda: get_status(job_id=job_a).get("status") == "completed"
        and get_status(job_id=job_b).get("status") == "completed",
    )

    # inbox-A only returns its own job.
    out_a = recall(inbox_id="inbox-A")
    assert [r["job_id"] for r in out_a["results"]] == [job_a]

    # inbox-B still has its job (inbox-A drain shouldn't have touched it).
    out_b = recall(inbox_id="inbox-B")
    assert [r["job_id"] for r in out_b["results"]] == [job_b]


def test_inbox_empty_returns_empty_results_and_no_marks(fake_config: HarbormasterConfig):
    mcp = build_server(fake_config)
    recall = _tools(mcp)["recall_pending_results"].fn
    out = recall(inbox_id="nothing-here")
    assert out == {"inbox_id": "nothing-here", "results": [], "marked_read": 0}

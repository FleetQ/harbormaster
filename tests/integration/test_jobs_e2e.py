"""End-to-end test for the async delegate path using fake_claude
(v22.0.0a2).

Spawns a real subprocess via the fake_claude shim so the full chain
runs: ``delegate_task(mode="async")`` → JobStore.enqueue → JobWorker
claims → run_backend → fake claude -p → JSON parse → JobStore.complete
→ ``get_delegated_task`` returns ``completed``.

Mirrors the existing fake-claude pattern in
``test_e2e_fake_claude.py`` so failure modes carry the same signature.
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
def project_dir(tmp_path: Path) -> Path:
    code = tmp_path / "code"
    proj = code / "myproj"
    proj.mkdir(parents=True)
    (proj / "CLAUDE.md").write_text("# fake project", encoding="utf-8")
    return proj


@pytest.fixture
def fake_config(tmp_path: Path, project_dir: Path, monkeypatch) -> HarbormasterConfig:
    monkeypatch.setenv("HARBORMASTER_JOBS_DB", str(tmp_path / "jobs.db"))
    return HarbormasterConfig(
        projects=ProjectsConfig(glob=[f"{tmp_path}/code/*"]),
        backends={
            "claude": BackendConfig(
                binary=str(FAKE_CLAUDE),
                timeout_local=10,
            )
        },
    )


@pytest.fixture(autouse=True)
def _isolate_subsystem():
    """Each test starts from a fresh subsystem singleton."""
    yield
    shutdown_subsystem()


def _wait_until(predicate, timeout: float = 5.0, poll: float = 0.05) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate():
            return True
        time.sleep(poll)
    return False


def _tools_by_name(mcp):
    return {t.name: t for t in mcp._tool_manager.list_tools()}


def test_async_delegate_completes_through_fake_claude(fake_config: HarbormasterConfig):
    mcp = build_server(fake_config)
    tools = _tools_by_name(mcp)
    delegate = tools["delegate_task"].fn
    get_status = tools["get_delegated_task"].fn

    handle = delegate(
        name="myproj",
        task="audit",
        deliverable="report",
        allow_writes=False,
        mode="async",
        inbox_id="sprint-X",
    )
    assert handle.startswith("queued d_")
    assert "inbox=sprint-X" in handle

    # Pull job_id out of the handle string. Format:
    # "queued d_<hex> (inbox=...). Poll with ..."
    job_id = handle.split(" ", 2)[1]

    assert _wait_until(
        lambda: get_status(job_id=job_id).get("status") == "completed",
    ), f"job did not complete: latest={get_status(job_id=job_id)}"

    final = get_status(job_id=job_id)
    assert final["status"] == "completed"
    assert "FAKE_CLAUDE answered" in (final["output"] or "")
    assert final["duration_ms"] is not None and final["duration_ms"] >= 0
    assert final["error"] is None
    assert final["inbox_id"] == "sprint-X"


def test_async_delegate_records_failure_on_garbage_claude(
    fake_config: HarbormasterConfig, monkeypatch,
):
    monkeypatch.setenv("HARBORMASTER_FAKE_CLAUDE_FAIL", "garbage")
    mcp = build_server(fake_config)
    tools = _tools_by_name(mcp)
    delegate = tools["delegate_task"].fn
    get_status = tools["get_delegated_task"].fn

    handle = delegate(
        name="myproj",
        task="audit",
        deliverable="report",
        allow_writes=False,
        mode="async",
    )
    job_id = handle.split(" ", 2)[1]

    assert _wait_until(
        lambda: get_status(job_id=job_id).get("status") == "failed",
        timeout=6.0,
    )

    final = get_status(job_id=job_id)
    assert final["status"] == "failed"
    assert "Error:" in (final["error"] or "")
    # cid is minted on BackendError; parse failure path emits one.
    assert final["cid"] is not None


def test_get_delegated_task_returns_not_found_for_unknown(fake_config: HarbormasterConfig):
    mcp = build_server(fake_config)
    get_status = _tools_by_name(mcp)["get_delegated_task"].fn
    out = get_status(job_id="d_nonexistent")
    assert out == {"error": "not_found", "job_id": "d_nonexistent"}

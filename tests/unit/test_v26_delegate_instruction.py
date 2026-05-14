"""v26.0.0 — delegate_task in instruction mode."""
from __future__ import annotations

from pathlib import Path

import pytest

from harbormaster.config import DelegateConfig, HarbormasterConfig, ProjectsConfig
from harbormaster.instruction import INSTRUCTION_MARKER
from harbormaster.jobs.schema import (
    STATUS_AWAITING_CALLER,
)
from harbormaster.server import build_server


def _tools(mcp):
    return {t.name: t for t in mcp._tool_manager.list_tools()}


@pytest.fixture
def jobs_db(tmp_path, monkeypatch):
    db = tmp_path / "jobs.db"
    monkeypatch.setenv("HARBORMASTER_JOBS_DB", str(db))
    from harbormaster.jobs import subsystem as _sub
    if _sub._singleton is not None:
        _sub.shutdown_subsystem()
    yield db
    if _sub._singleton is not None:
        _sub.shutdown_subsystem()


@pytest.fixture
def project_dir(tmp_path):
    """Lay out a fake project so resolve_project succeeds. _is_project
    requires either a .git dir or a CLAUDE.md file."""
    p = tmp_path / "fakeproj"
    p.mkdir()
    (p / "CLAUDE.md").write_text("# fake project marker\n")
    return p


def _cfg_with_project(project_dir: Path, **delegate_overrides):
    return HarbormasterConfig(
        projects=ProjectsConfig(glob=[str(project_dir.parent) + "/*"]),
        delegate=DelegateConfig(**delegate_overrides),
    )


def test_sync_instruction_returns_packet_no_subprocess(
    jobs_db, project_dir, monkeypatch,
):
    cfg = _cfg_with_project(project_dir)  # default execution_mode=instruction
    # Sentinel: if subprocess path runs, run_backend would fire.
    from harbormaster.tools import _helpers as _h
    monkeypatch.setattr(
        _h, "run_backend",
        lambda **_: pytest.fail("run_backend must not be called in instruction mode"),
    )

    fn = _tools(build_server(cfg))["delegate_task"].fn
    out = fn(
        name=project_dir.name,
        task="refactor x",
        deliverable="diff",
        allow_writes=True,
    )
    assert INSTRUCTION_MARKER in out
    assert "delegate-writes" in out


def test_sync_subprocess_unchanged(jobs_db, project_dir, monkeypatch):
    """Opt-back to subprocess mode preserves v25 behavior."""
    cfg = _cfg_with_project(project_dir, execution_mode="subprocess")
    from harbormaster.tools import _helpers as _h
    captured: dict[str, str] = {}

    def fake(*, prompt, **_):
        captured["prompt"] = prompt
        return "subprocess_ok_result"

    monkeypatch.setattr(_h, "run_backend", fake)

    fn = _tools(build_server(cfg))["delegate_task"].fn
    out = fn(
        name=project_dir.name, task="t", deliverable="d",
        allow_writes=False,
    )
    assert out == "subprocess_ok_result"
    assert "Read-only mode" in captured["prompt"]


def test_async_instruction_returns_handle_and_packet_via_get(
    jobs_db, project_dir,
):
    cfg = _cfg_with_project(project_dir)
    mcp = build_server(cfg)
    delegate_fn = _tools(mcp)["delegate_task"].fn
    get_fn = _tools(mcp)["get_delegated_task"].fn

    out = delegate_fn(
        name=project_dir.name, task="t", deliverable="d",
        allow_writes=False, mode="async",
    )
    assert out.startswith("queued ")
    assert "instruction mode" in out

    # Extract the job_id from the handle string.
    parts = out.split()
    job_id = parts[1]

    payload = get_fn(job_id=job_id)
    assert payload["status"] == STATUS_AWAITING_CALLER
    assert "instruction_packet" in payload
    assert INSTRUCTION_MARKER in payload["instruction_packet"]


def test_async_subprocess_unchanged(jobs_db, project_dir, monkeypatch):
    """Opt back to subprocess: async path enqueues a QUEUED row for
    the JobWorker, not an awaiting_caller row."""
    cfg = _cfg_with_project(project_dir, execution_mode="subprocess")
    # Block the worker from actually picking the row up so we can
    # inspect the queued state.
    from harbormaster.jobs import worker as _worker
    monkeypatch.setattr(_worker, "run_backend", lambda **_: "ok")

    mcp = build_server(cfg)
    delegate_fn = _tools(mcp)["delegate_task"].fn
    out = delegate_fn(
        name=project_dir.name, task="t", deliverable="d",
        mode="async",
    )
    assert out.startswith("queued ")
    assert "instruction mode" not in out


def test_ssh_host_forces_subprocess_in_instruction_mode(
    jobs_db, project_dir, monkeypatch,
):
    """Even with execution_mode=instruction, an SSH host falls back to
    subprocess at the tool layer."""
    cfg = _cfg_with_project(project_dir)
    from harbormaster.tools import _helpers as _h
    called = {"subprocess": False}

    def fake_run_backend(**_kwargs):
        called["subprocess"] = True
        return "remote_ok"

    monkeypatch.setattr(_h, "run_backend", fake_run_backend)

    fn = _tools(build_server(cfg))["delegate_task"].fn
    out = fn(
        name=project_dir.name, task="t", deliverable="d",
        host="some-remote",
    )
    assert called["subprocess"], "Remote target must hit subprocess path"
    assert out == "remote_ok"


def test_packet_includes_writes_kind_for_allow_writes(
    jobs_db, project_dir,
):
    cfg = _cfg_with_project(project_dir)
    fn = _tools(build_server(cfg))["delegate_task"].fn
    out = fn(
        name=project_dir.name, task="t", deliverable="d",
        allow_writes=True, auto_commit=True,
    )
    assert "delegate-writes-auto-commit" in out


def test_recovered_packet_preserves_read_only_suffix(jobs_db, project_dir):
    """v26 fix: recovered packet via get_delegated_task must contain
    the read-only role suffix when the job was enqueued read-only.
    Otherwise an Agent re-spawned from the recovery would freely
    edit files, violating the caller's authorisation."""
    cfg = _cfg_with_project(project_dir)
    mcp = build_server(cfg)
    delegate_fn = _tools(mcp)["delegate_task"].fn
    get_fn = _tools(mcp)["get_delegated_task"].fn

    out = delegate_fn(
        name=project_dir.name, task="t", deliverable="d",
        allow_writes=False, mode="async",
    )
    job_id = out.split()[1]
    payload = get_fn(job_id=job_id)
    assert "instruction_packet" in payload
    packet = payload["instruction_packet"]
    assert "Read-only mode" in packet
    assert "Do NOT edit files" in packet


def test_recovered_packet_preserves_writes_suffix(jobs_db, project_dir):
    """Counterpart: writes-allowed async delegate. Recovered packet
    must carry the writes suffix (and NOT the read-only suffix)."""
    cfg = _cfg_with_project(project_dir)
    mcp = build_server(cfg)
    delegate_fn = _tools(mcp)["delegate_task"].fn
    get_fn = _tools(mcp)["get_delegated_task"].fn

    out = delegate_fn(
        name=project_dir.name, task="t", deliverable="d",
        allow_writes=True, mode="async",
    )
    job_id = out.split()[1]
    payload = get_fn(job_id=job_id)
    packet = payload["instruction_packet"]
    assert "You may edit files" in packet
    assert "Read-only mode" not in packet


def test_packet_max_turns_propagated(jobs_db, project_dir):
    cfg = _cfg_with_project(project_dir)
    fn = _tools(build_server(cfg))["delegate_task"].fn
    out = fn(
        name=project_dir.name, task="t", deliverable="d",
        max_turns=80,
    )
    assert "Max turns hint**: `80`" in out

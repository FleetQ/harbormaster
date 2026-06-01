"""v27.0.0 — get_delegated_task rebuilds the packet with the row's adapter."""
from __future__ import annotations

from pathlib import Path

import pytest

from harbormaster.config import DelegateConfig, HarbormasterConfig, ProjectsConfig
from harbormaster.instruction import INSTRUCTION_MARKER
from harbormaster.jobs.schema import STATUS_AWAITING_CALLER
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
    p = tmp_path / "proj"
    p.mkdir()
    (p / "CLAUDE.md").write_text("# marker\n")
    return p


def _cfg(root: Path, **overrides):
    return HarbormasterConfig(
        projects=ProjectsConfig(glob=[str(root) + "/*"]),
        delegate=DelegateConfig(**overrides),
    )


def test_recovery_uses_codex_adapter(jobs_db, project_dir):
    cfg = _cfg(project_dir.parent)
    from harbormaster.jobs import get_subsystem
    job = get_subsystem(cfg).store.enqueue(
        project=project_dir.name, host=None, task="t", deliverable="d",
        allow_writes=False, model=None,
        execution_mode="instruction",
        initial_status=STATUS_AWAITING_CALLER,
        rendered_prompt="Do the thing.",
        orchestrator="codex",
    )
    fn = _tools(build_server(cfg))["get_delegated_task"].fn
    payload = fn(job_id=job.id)
    pkt = payload["instruction_packet"]
    assert INSTRUCTION_MARKER in pkt
    assert "Codex" in pkt
    assert "subagent_type" not in pkt


def test_recovery_legacy_null_orchestrator_uses_claude(jobs_db, project_dir):
    cfg = _cfg(project_dir.parent)
    from harbormaster.jobs import get_subsystem
    job = get_subsystem(cfg).store.enqueue(
        project=project_dir.name, host=None, task="t", deliverable="d",
        allow_writes=False, model=None,
        execution_mode="instruction",
        initial_status=STATUS_AWAITING_CALLER,
        rendered_prompt="Do the thing.",
        # orchestrator omitted → NULL (pre-v27 row shape)
    )
    fn = _tools(build_server(cfg))["get_delegated_task"].fn
    payload = fn(job_id=job.id)
    pkt = payload["instruction_packet"]
    assert "## Step 1 — Spawn Agent" in pkt  # claude shape
    assert "subagent_type" in pkt

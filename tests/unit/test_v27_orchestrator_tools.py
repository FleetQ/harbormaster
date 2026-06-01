"""v27.0.0 — orchestrator param wiring through ask / delegate / fan_out."""
from __future__ import annotations

from pathlib import Path

import pytest

from harbormaster.config import DelegateConfig, HarbormasterConfig, ProjectsConfig
from harbormaster.instruction import INSTRUCTION_MARKER
from harbormaster.jobs.schema import STATUS_AWAITING_CALLER, STATUS_QUEUED
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


@pytest.fixture
def two_projects(tmp_path):
    a = tmp_path / "proj-alpha"
    b = tmp_path / "proj-beta"
    a.mkdir()
    b.mkdir()
    (a / "CLAUDE.md").write_text("# alpha\n")
    (b / "CLAUDE.md").write_text("# beta\n")
    return tmp_path, ["proj-alpha", "proj-beta"]


def _cfg(root: Path, **overrides):
    return HarbormasterConfig(
        projects=ProjectsConfig(glob=[str(root) + "/*"]),
        delegate=DelegateConfig(**overrides),
    )


def _rows(cfg):
    from harbormaster.jobs import get_subsystem
    return get_subsystem(cfg).store.list_recent(limit=20)


# ---- ask_project ---------------------------------------------------------

def test_ask_orchestrator_codex_renders_codex_packet(jobs_db, project_dir):
    cfg = _cfg(project_dir.parent)
    fn = _tools(build_server(cfg))["ask_project"].fn
    out = fn(name=project_dir.name, question="q", orchestrator="codex")
    assert INSTRUCTION_MARKER in out
    assert "Codex" in out
    assert "subagent_type" not in out
    row = next(r for r in _rows(cfg) if r.status == STATUS_AWAITING_CALLER)
    assert row.orchestrator == "codex"


def test_ask_default_is_claude_packet(jobs_db, project_dir):
    cfg = _cfg(project_dir.parent)  # orchestrator=auto, no client detection
    fn = _tools(build_server(cfg))["ask_project"].fn
    out = fn(name=project_dir.name, question="q")
    # claude packet shape (v26 byte-for-byte path)
    assert "## Step 1 — Spawn Agent" in out
    assert "subagent_type" in out
    row = next(r for r in _rows(cfg) if r.status == STATUS_AWAITING_CALLER)
    assert row.orchestrator == "claude"


def test_ask_unknown_orchestrator_falls_back_to_subprocess(
    jobs_db, project_dir, monkeypatch,
):
    cfg = _cfg(project_dir.parent)
    from harbormaster.tools import _helpers as _h
    monkeypatch.setattr(_h, "run_backend", lambda **_: "subprocess_result")

    fn = _tools(build_server(cfg))["ask_project"].fn
    out = fn(name=project_dir.name, question="q", orchestrator="bogus")
    assert out == "subprocess_result"
    # no awaiting_caller row created
    assert not any(r.status == STATUS_AWAITING_CALLER for r in _rows(cfg))


# ---- delegate_task -------------------------------------------------------

def test_delegate_sync_orchestrator_gemini(jobs_db, project_dir):
    cfg = _cfg(project_dir.parent)
    fn = _tools(build_server(cfg))["delegate_task"].fn
    out = fn(
        name=project_dir.name, task="do x", deliverable="done",
        orchestrator="gemini",
    )
    assert INSTRUCTION_MARKER in out
    assert "@generalist" in out
    row = next(r for r in _rows(cfg) if r.status == STATUS_AWAITING_CALLER)
    assert row.orchestrator == "gemini"


def test_delegate_async_orchestrator_persisted(jobs_db, project_dir):
    cfg = _cfg(project_dir.parent)
    fn = _tools(build_server(cfg))["delegate_task"].fn
    out = fn(
        name=project_dir.name, task="do x", deliverable="done",
        mode="async", orchestrator="gemini",
    )
    assert out.startswith("queued ")
    row = next(r for r in _rows(cfg) if r.status == STATUS_AWAITING_CALLER)
    assert row.orchestrator == "gemini"
    assert row.execution_mode == "instruction"


def test_delegate_async_unknown_orchestrator_subprocess(jobs_db, project_dir):
    cfg = _cfg(project_dir.parent)
    fn = _tools(build_server(cfg))["delegate_task"].fn
    out = fn(
        name=project_dir.name, task="do x", deliverable="done",
        mode="async", orchestrator="bogus",
    )
    assert out.startswith("queued ")
    rows = _rows(cfg)
    # subprocess-async row: queued, no orchestrator, no awaiting_caller
    assert any(
        r.status == STATUS_QUEUED and r.execution_mode == "subprocess"
        and r.orchestrator is None
        for r in rows
    )
    assert not any(r.status == STATUS_AWAITING_CALLER for r in rows)


# ---- fan_out_ask ---------------------------------------------------------

def test_fan_out_orchestrator_codex(jobs_db, two_projects):
    root, names = two_projects
    cfg = _cfg(root)
    fn = _tools(build_server(cfg))["fan_out_ask"].fn
    out = fn(question="what?", project_filter=names, orchestrator="codex")
    assert INSTRUCTION_MARKER in out
    assert "Codex" in out
    awaiting = [r for r in _rows(cfg) if r.status == STATUS_AWAITING_CALLER]
    assert len(awaiting) == 2
    assert all(r.orchestrator == "codex" for r in awaiting)
    # all share one batch_id (v26.1 correlation preserved)
    assert len({r.batch_id for r in awaiting}) == 1


def test_fan_out_unknown_orchestrator_subprocess(
    jobs_db, two_projects, monkeypatch,
):
    root, names = two_projects
    cfg = _cfg(root)
    from harbormaster.tools import fan_out as _fan_out
    monkeypatch.setattr(
        _fan_out, "run_backend",
        lambda **kw: f"sub_{kw['name']}",
    )
    fn = _tools(build_server(cfg))["fan_out_ask"].fn
    out = fn(question="what?", project_filter=names, orchestrator="bogus")
    assert INSTRUCTION_MARKER not in out
    assert "sub_proj-alpha" in out
    assert not any(r.status == STATUS_AWAITING_CALLER for r in _rows(cfg))

"""v26.0.0 — fan_out_ask in instruction mode."""
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


def test_fan_out_instruction_returns_batch_packet(jobs_db, two_projects):
    root, names = two_projects
    cfg = _cfg(root)
    fn = _tools(build_server(cfg))["fan_out_ask"].fn
    out = fn(question="what?", project_filter=names)
    assert INSTRUCTION_MARKER in out
    assert "fan-out" in out
    assert "proj-alpha" in out
    assert "proj-beta" in out


def test_fan_out_instruction_creates_n_rows(jobs_db, two_projects):
    root, names = two_projects
    cfg = _cfg(root)
    fn = _tools(build_server(cfg))["fan_out_ask"].fn
    fn(question="what?", project_filter=names)
    from harbormaster.jobs import get_subsystem
    rows = get_subsystem(cfg).store.list_recent(limit=10)
    awaiting = [
        r for r in rows
        if r.status == STATUS_AWAITING_CALLER
        and r.execution_mode == "instruction"
    ]
    assert len(awaiting) == 2
    projects = {r.project for r in awaiting}
    assert projects == set(names)


def test_fan_out_subprocess_unchanged(
    jobs_db, two_projects, monkeypatch,
):
    root, names = two_projects
    cfg = _cfg(root, execution_mode="subprocess")
    # fan_out.py imports run_backend at module scope — must monkeypatch
    # the module's own binding, not _helpers.run_backend.
    from harbormaster.tools import fan_out as _fan_out

    def fake(**kwargs):
        return f"subprocess_answer_for_{kwargs['name']}"

    monkeypatch.setattr(_fan_out, "run_backend", fake)

    fn = _tools(build_server(cfg))["fan_out_ask"].fn
    out = fn(question="what?", project_filter=names)
    assert INSTRUCTION_MARKER not in out
    assert "subprocess_answer_for_proj-alpha" in out
    assert "subprocess_answer_for_proj-beta" in out


def test_fan_out_mixed_remote_falls_back_to_subprocess(
    jobs_db, two_projects, monkeypatch,
):
    """When any target is remote, the whole fan-out runs subprocess —
    instruction mode doesn't produce hybrid responses."""
    root, names = two_projects
    cfg = _cfg(root)  # default instruction mode

    from harbormaster.tools import fan_out as _fan_out
    calls = []

    def fake(**kwargs):
        calls.append(kwargs["name"])
        return f"out_for_{kwargs['name']}"

    monkeypatch.setattr(_fan_out, "run_backend", fake)

    fn = _tools(build_server(cfg))["fan_out_ask"].fn
    out = fn(
        question="what?", project_filter=names,
        host_filter=["local", "friday"],
    )
    # subprocess path was used (not instruction).
    assert INSTRUCTION_MARKER not in out
    # Each target executed; remote and local both invoked run_backend.
    assert len(calls) >= 2


def test_fan_out_synthesize_flag_carries_to_packet(jobs_db, two_projects):
    root, names = two_projects
    cfg = _cfg(root)
    fn = _tools(build_server(cfg))["fan_out_ask"].fn
    out = fn(
        question="what?", project_filter=names,
        synthesize=True, synthesis_max_turns=8,
    )
    assert INSTRUCTION_MARKER in out
    assert "Synthesize**: `True`" in out
    assert "max_turns=8" in out

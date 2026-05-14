"""v26.0.0 — ask_project in instruction mode."""
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
    p = tmp_path / "askproj"
    p.mkdir()
    (p / "CLAUDE.md").write_text("# marker\n")
    return p


def _cfg(project_dir: Path, **overrides):
    return HarbormasterConfig(
        projects=ProjectsConfig(glob=[str(project_dir.parent) + "/*"]),
        delegate=DelegateConfig(**overrides),
    )


def test_ask_instruction_returns_packet_no_subprocess(
    jobs_db, project_dir, monkeypatch,
):
    cfg = _cfg(project_dir)  # default instruction mode
    from harbormaster.tools import _helpers as _h
    monkeypatch.setattr(
        _h, "run_backend",
        lambda **_: pytest.fail("subprocess path must not run"),
    )

    fn = _tools(build_server(cfg))["ask_project"].fn
    out = fn(name=project_dir.name, question="what does this do?")
    assert INSTRUCTION_MARKER in out
    assert "**Kind**: `ask`" in out


def test_ask_subprocess_unchanged(jobs_db, project_dir, monkeypatch):
    cfg = _cfg(project_dir, execution_mode="subprocess")
    from harbormaster.tools import _helpers as _h
    captured: dict[str, str] = {}

    def fake(*, prompt, **_):
        captured["prompt"] = prompt
        return "ok_subprocess"

    monkeypatch.setattr(_h, "run_backend", fake)

    fn = _tools(build_server(cfg))["ask_project"].fn
    out = fn(name=project_dir.name, question="what does this do?")
    assert out == "ok_subprocess"
    assert "Return a concise markdown summary under 500 words" in captured["prompt"]


def test_ask_remote_host_forces_subprocess(jobs_db, project_dir, monkeypatch):
    cfg = _cfg(project_dir)  # default instruction
    from harbormaster.tools import _helpers as _h
    called = {"subprocess": False}

    def fake(**_):
        called["subprocess"] = True
        return "remote_ok"

    monkeypatch.setattr(_h, "run_backend", fake)

    fn = _tools(build_server(cfg))["ask_project"].fn
    out = fn(
        name=project_dir.name, question="q", host="someserver",
    )
    assert called["subprocess"]
    assert out == "remote_ok"


def test_ask_instruction_creates_awaiting_caller_row(jobs_db, project_dir):
    cfg = _cfg(project_dir)
    fn = _tools(build_server(cfg))["ask_project"].fn
    fn(name=project_dir.name, question="status?")

    from harbormaster.jobs import get_subsystem
    rows = get_subsystem(cfg).store.list_recent(limit=10)
    assert any(
        r.status == STATUS_AWAITING_CALLER
        and r.execution_mode == "instruction"
        and r.project == project_dir.name
        for r in rows
    )


def test_ask_packet_embeds_500_word_suffix(jobs_db, project_dir):
    cfg = _cfg(project_dir)
    fn = _tools(build_server(cfg))["ask_project"].fn
    out = fn(name=project_dir.name, question="quick question")
    assert "under 500 words" in out

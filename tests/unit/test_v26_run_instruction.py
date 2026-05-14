"""v26.0.0 — run_instruction / run_backend_or_instruction tests in _helpers."""
from __future__ import annotations

import time
from pathlib import Path

import pytest

from harbormaster.config import DelegateConfig, HarbormasterConfig, ProjectsConfig
from harbormaster.instruction import is_instruction_packet
from harbormaster.jobs.schema import STATUS_AWAITING_CALLER
from harbormaster.tools._helpers import (
    run_backend_or_instruction,
    run_instruction,
)


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
    p = tmp_path / "myproj"
    p.mkdir()
    (p / "CLAUDE.md").write_text("# myproj\n")
    return p


def _cfg(project_dir: Path, **delegate_overrides):
    return HarbormasterConfig(
        projects=ProjectsConfig(glob=[str(project_dir.parent) + "/*"]),
        delegate=DelegateConfig(**delegate_overrides),
    )


def test_run_instruction_returns_packet_with_marker(jobs_db, project_dir):
    cfg = _cfg(project_dir)
    out = run_instruction(
        name=project_dir.name,
        prompt="do x",
        max_turns=10,
        host=None,
        config=cfg,
        label_prefix="delegate",
    )
    assert is_instruction_packet(out)


def test_run_instruction_creates_awaiting_caller_row(jobs_db, project_dir):
    cfg = _cfg(project_dir)
    out = run_instruction(
        name=project_dir.name, prompt="p",
        max_turns=10, host=None, config=cfg,
        label_prefix="delegate",
    )
    from harbormaster.jobs import get_subsystem
    rows = get_subsystem(cfg).store.list_recent(limit=5)
    assert any(
        r.status == STATUS_AWAITING_CALLER
        and r.execution_mode == "instruction"
        for r in rows
    )
    # Packet must reference the same job_id we created.
    from harbormaster.instruction import extract_job_id
    job_id = extract_job_id(out)
    assert job_id is not None
    assert any(r.id == job_id for r in rows)


def test_run_instruction_invalid_project_name_returns_error(jobs_db, project_dir):
    cfg = _cfg(project_dir)
    out = run_instruction(
        name="../escape", prompt="p", max_turns=10, host=None,
        config=cfg, label_prefix="delegate",
    )
    assert out.startswith("Error:")


def test_run_instruction_unknown_project_returns_error(jobs_db, project_dir):
    cfg = _cfg(project_dir)
    out = run_instruction(
        name="does-not-exist", prompt="p", max_turns=10, host=None,
        config=cfg, label_prefix="delegate",
    )
    assert out.startswith("Error:")


def test_run_instruction_fast(jobs_db, project_dir):
    """No LLM call → must complete well under 100ms."""
    cfg = _cfg(project_dir)
    start = time.monotonic()
    out = run_instruction(
        name=project_dir.name, prompt="p",
        max_turns=10, host=None, config=cfg,
        label_prefix="delegate",
    )
    elapsed = time.monotonic() - start
    assert is_instruction_packet(out)
    assert elapsed < 1.0  # Generous bound; in practice << 100ms.


def test_dispatcher_picks_instruction_for_local(jobs_db, project_dir, monkeypatch):
    cfg = _cfg(project_dir)  # default instruction
    from harbormaster.tools import _helpers as _h

    monkeypatch.setattr(
        _h, "run_backend",
        lambda **_: pytest.fail("subprocess must not run for local-instruction"),
    )

    out = run_backend_or_instruction(
        name=project_dir.name, prompt="p", max_turns=10,
        host=None, config=cfg, label_prefix="delegate",
    )
    assert is_instruction_packet(out)


def test_dispatcher_picks_subprocess_for_remote(jobs_db, project_dir, monkeypatch):
    cfg = _cfg(project_dir)  # default instruction
    from harbormaster.tools import _helpers as _h
    called = {"subprocess": False}

    def fake_run_backend(**_):
        called["subprocess"] = True
        return "remote_subprocess_result"

    monkeypatch.setattr(_h, "run_backend", fake_run_backend)

    out = run_backend_or_instruction(
        name=project_dir.name, prompt="p", max_turns=10,
        host="friday", config=cfg, label_prefix="delegate",
    )
    assert called["subprocess"]
    assert out == "remote_subprocess_result"


def test_dispatcher_picks_subprocess_when_configured(
    jobs_db, project_dir, monkeypatch,
):
    cfg = _cfg(project_dir, execution_mode="subprocess")
    from harbormaster.tools import _helpers as _h
    called = {"subprocess": False}

    def fake_run_backend(**_):
        called["subprocess"] = True
        return "local_subprocess_result"

    monkeypatch.setattr(_h, "run_backend", fake_run_backend)

    out = run_backend_or_instruction(
        name=project_dir.name, prompt="p", max_turns=10,
        host=None, config=cfg, label_prefix="delegate",
    )
    assert called["subprocess"]
    assert out == "local_subprocess_result"

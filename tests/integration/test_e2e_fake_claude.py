"""End-to-end tests using a fake `claude` shim binary.

Closes the test gap flagged in the v1.0.0a2 retro: every previous test
either mocked subprocess.run or skipped behind HARBORMASTER_RUN_LIVE=1.
These tests spawn a real subprocess (a Python script in tests/fixtures/)
that mimics the claude -p JSON contract — exercising the whole subprocess
spawn → JSON parse → BackendResult → MCP envelope chain.

Each test creates an isolated tmp_path project tree and a config wired to
point at the fake_claude.py shim, so they're CI-runnable on any host with
Python 3.11+. No Anthropic seat needed.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from harbormaster.config import (
    BackendConfig,
    DelegateConfig,
    HarbormasterConfig,
    ProjectsConfig,
)
from harbormaster.server import build_server

FAKE_CLAUDE = Path(__file__).resolve().parent.parent / "fixtures" / "fake_claude.py"


@pytest.fixture
def project_dir(tmp_path: Path) -> Path:
    """Create a single fake project at tmp_path/code/myproj/ with a CLAUDE.md."""
    code = tmp_path / "code"
    proj = code / "myproj"
    proj.mkdir(parents=True)
    (proj / "CLAUDE.md").write_text("# fake project", encoding="utf-8")
    return proj


@pytest.fixture
def fake_config(tmp_path: Path, project_dir: Path) -> HarbormasterConfig:
    return HarbormasterConfig(
        projects=ProjectsConfig(glob=[f"{tmp_path}/code/*"]),
        backends={
            "claude": BackendConfig(
                binary=str(FAKE_CLAUDE),
                timeout_local=10,  # plenty for the shim
            )
        },
        # v26.0.0 — these tests exercise the real subprocess path
        # against a fake-claude shim. The v26 default execution_mode
        # is "instruction" (returns a packet instead of spawning the
        # binary); pin to "subprocess" here so the fake-claude harness
        # is actually invoked. Instruction mode has its own dedicated
        # coverage in tests/unit/test_v26_*.py.
        delegate=DelegateConfig(execution_mode="subprocess"),
    )


def _ask_project(config: HarbormasterConfig, name: str, question: str) -> str:
    mcp = build_server(config)
    fn = next(t for t in mcp._tool_manager.list_tools() if t.name == "ask_project").fn
    return fn(name=name, question=question, max_turns=1)


# ----- happy path ------------------------------------------------------------


def test_ask_project_real_subprocess_returns_canned_answer(fake_config: HarbormasterConfig):
    out = _ask_project(fake_config, "myproj", "what's the deal?")
    assert "FAKE_CLAUDE answered" in out
    assert "what's the deal?" in out


def test_ask_project_runs_in_project_cwd(fake_config: HarbormasterConfig, project_dir: Path):
    """Fake claude echoes its cwd; assert harbormaster spawned it inside the project."""
    out = _ask_project(fake_config, "myproj", "where am I?")
    assert str(project_dir.resolve()) in out


def test_fan_out_ask_real_subprocess(fake_config: HarbormasterConfig, tmp_path: Path):
    """Add a second project so fan_out has multiple targets."""
    second = tmp_path / "code" / "other"
    second.mkdir(parents=True)
    (second / "CLAUDE.md").write_text("# 2nd project", encoding="utf-8")

    mcp = build_server(fake_config)
    fn = next(t for t in mcp._tool_manager.list_tools() if t.name == "fan_out_ask").fn
    out = fn(question="hi", project_filter=None, host_filter=None, max_concurrency=2, max_turns=1)
    # Both projects answered
    assert "## myproj" in out
    assert "## other" in out
    assert "Success:** 2/2" in out


def test_fan_out_ask_with_synthesize(fake_config: HarbormasterConfig, tmp_path: Path):
    """synthesize=True triggers an extra claude -p call producing a synthesis
    section. The fake shim echoes the synthesis prompt back, so the synthesis
    section contains evidence of the cross-target prompt being assembled."""
    second = tmp_path / "code" / "other"
    second.mkdir(parents=True)
    (second / "CLAUDE.md").write_text("# 2nd project", encoding="utf-8")

    mcp = build_server(fake_config)
    fn = next(t for t in mcp._tool_manager.list_tools() if t.name == "fan_out_ask").fn
    out = fn(
        question="how does X work?",
        project_filter=None,
        host_filter=None,
        max_concurrency=2,
        max_turns=1,
        synthesize=True,
        synthesis_max_turns=1,
    )
    assert "## Synthesis" in out
    # Synthesis section comes before per-target sections
    assert out.find("## Synthesis") < out.find("## myproj")
    # Per-target sections still present
    assert "## myproj" in out
    assert "## other" in out


def test_fan_out_ask_synthesize_skipped_on_all_errors(fake_config: HarbormasterConfig, monkeypatch):
    """When every target errors, synthesis has nothing to summarize and
    surfaces a 'Synthesis skipped:' line instead of crashing or hanging."""
    monkeypatch.setenv("HARBORMASTER_FAKE_CLAUDE_FAIL", "exit2")
    mcp = build_server(fake_config)
    fn = next(t for t in mcp._tool_manager.list_tools() if t.name == "fan_out_ask").fn
    out = fn(
        question="?",
        project_filter=None,
        host_filter=None,
        max_concurrency=1,
        max_turns=1,
        synthesize=True,
        synthesis_max_turns=1,
    )
    assert "Synthesis skipped" in out


# ----- failure-mode coverage -------------------------------------------------


def test_backend_timeout_surfaces_as_error(fake_config: HarbormasterConfig, monkeypatch):
    """HARBORMASTER_FAKE_CLAUDE_FAIL=timeout makes the shim sleep 120s; tighten
    the local timeout so we trigger the timeout path quickly."""
    fake_config.backends["claude"].timeout_local = 2  # type: ignore[misc]
    monkeypatch.setenv("HARBORMASTER_FAKE_CLAUDE_FAIL", "timeout")
    out = _ask_project(fake_config, "myproj", "stalls")
    assert out.startswith("Error:")
    assert "timeout" in out.lower()


def test_backend_nonzero_exit_surfaces_as_error(fake_config: HarbormasterConfig, monkeypatch):
    monkeypatch.setenv("HARBORMASTER_FAKE_CLAUDE_FAIL", "exit2")
    out = _ask_project(fake_config, "myproj", "fail")
    assert out.startswith("Error:")
    assert "exit 2" in out
    assert "simulated failure" in out


def test_backend_garbage_stdout_surfaces_as_parse_error(fake_config: HarbormasterConfig, monkeypatch):
    monkeypatch.setenv("HARBORMASTER_FAKE_CLAUDE_FAIL", "garbage")
    out = _ask_project(fake_config, "myproj", "what")
    assert out.startswith("Error:")
    assert "non-JSON" in out


def test_backend_empty_result_surfaces_as_parse_error(fake_config: HarbormasterConfig, monkeypatch):
    monkeypatch.setenv("HARBORMASTER_FAKE_CLAUDE_FAIL", "empty")
    out = _ask_project(fake_config, "myproj", "what")
    assert out.startswith("Error:")
    assert "empty" in out.lower()


# ----- traversal / unknown-project paths -------------------------------------


def test_ask_project_invalid_name_no_subprocess(fake_config: HarbormasterConfig):
    """validate_project_name short-circuits before any subprocess is spawned."""
    out = _ask_project(fake_config, "..", "shouldn't run")
    assert out.startswith("Error:")
    assert "invalid project name" in out


def test_ask_project_unknown_name(fake_config: HarbormasterConfig):
    out = _ask_project(fake_config, "definitely-not-real", "x")
    assert out.startswith("Error:")
    assert "not found" in out


# ----- fake_claude shim self-test --------------------------------------------


def test_fake_claude_shim_is_executable():
    """If the fixture lost its +x bit, every other e2e test would mysteriously
    fail with PermissionError. This test surfaces that root cause directly."""
    assert FAKE_CLAUDE.is_file()
    assert os.access(FAKE_CLAUDE, os.X_OK), \
        f"{FAKE_CLAUDE} is not executable; run `chmod +x` on the fixture"

"""Unit tests for fan_out_ask helpers (target resolution, report formatting)."""
from __future__ import annotations

from pathlib import Path

from harbormaster.config import HarbormasterConfig, HostConfig, ProjectsConfig
from harbormaster.server import build_server
from harbormaster.tools.fan_out import _build_targets, _format_report, _Target


def _make_project_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)
    (p / "CLAUDE.md").write_text("# test", encoding="utf-8")


# ----- registration ---------------------------------------------------------


def test_fan_out_ask_registered():
    mcp = build_server(HarbormasterConfig())
    names = {t.name for t in mcp._tool_manager.list_tools()}
    assert "fan_out_ask" in names


def test_fan_out_ask_signature():
    import inspect

    mcp = build_server(HarbormasterConfig())
    fn = next(t for t in mcp._tool_manager.list_tools() if t.name == "fan_out_ask").fn
    sig = inspect.signature(fn)
    expected = {"question", "project_filter", "host_filter", "max_concurrency", "max_turns"}
    assert expected == set(sig.parameters.keys())
    assert sig.parameters["max_concurrency"].default == 5
    assert sig.parameters["max_turns"].default == 3


# ----- _build_targets -------------------------------------------------------


def test_build_targets_local_no_filter(tmp_path: Path):
    base = tmp_path / "code"
    _make_project_dir(base / "alpha")
    _make_project_dir(base / "beta")
    cfg = HarbormasterConfig(projects=ProjectsConfig(glob=[f"{base}/*"]))
    targets = _build_targets(project_filter=None, host_filter=None, config=cfg)
    names = {t.project for t in targets}
    assert names == {"alpha", "beta"}
    assert all(t.host == "local" for t in targets)


def test_build_targets_local_with_project_filter(tmp_path: Path):
    base = tmp_path / "code"
    _make_project_dir(base / "alpha")
    _make_project_dir(base / "beta")
    _make_project_dir(base / "gamma")
    cfg = HarbormasterConfig(projects=ProjectsConfig(glob=[f"{base}/*"]))
    targets = _build_targets(project_filter=["alpha", "gamma"], host_filter=None, config=cfg)
    names = {t.project for t in targets}
    assert names == {"alpha", "gamma"}


def test_build_targets_remote_requires_project_filter(tmp_path: Path):
    cfg = HarbormasterConfig(
        projects=ProjectsConfig(glob=[f"{tmp_path}/*"]),
        hosts={"friday": HostConfig(ssh_host="f")},
    )
    # No project_filter → no remote targets produced (we can't enumerate)
    targets = _build_targets(
        project_filter=None,
        host_filter=["friday"],
        config=cfg,
    )
    assert targets == []


def test_build_targets_remote_with_project_filter(tmp_path: Path):
    cfg = HarbormasterConfig(
        projects=ProjectsConfig(glob=[f"{tmp_path}/*"]),
        hosts={"friday": HostConfig(ssh_host="f")},
    )
    targets = _build_targets(
        project_filter=["pinporn", "agent-fleet"],
        host_filter=["friday"],
        config=cfg,
    )
    assert {t.project for t in targets} == {"pinporn", "agent-fleet"}
    assert all(t.host == "friday" for t in targets)


def test_build_targets_mixed_local_and_remote(tmp_path: Path):
    base = tmp_path / "code"
    _make_project_dir(base / "alpha")
    cfg = HarbormasterConfig(
        projects=ProjectsConfig(glob=[f"{base}/*"]),
        hosts={"friday": HostConfig(ssh_host="f")},
    )
    targets = _build_targets(
        project_filter=["alpha"],
        host_filter=["local", "friday"],
        config=cfg,
    )
    pairs = {(t.host, t.project) for t in targets}
    assert pairs == {("local", "alpha"), ("friday", "alpha")}


# ----- _Target.label --------------------------------------------------------


def test_target_label_local_omits_host_prefix():
    assert _Target(host="local", project="myproj").label() == "myproj"


def test_target_label_remote_includes_host_prefix():
    assert _Target(host="friday", project="myproj").label() == "friday/myproj"


# ----- _format_report -------------------------------------------------------


def test_format_report_includes_question_and_per_target_sections():
    targets = [_Target("local", "alpha"), _Target("friday", "beta")]
    results = {targets[0]: "alpha says hi", targets[1]: "beta is up"}
    report = _format_report("how is auth?", targets, results)
    assert "# fan_out_ask: how is auth?" in report
    assert "## alpha" in report
    assert "## friday/beta" in report
    assert "alpha says hi" in report
    assert "beta is up" in report
    assert "Success:** 2/2" in report


def test_format_report_counts_errors_against_success():
    targets = [_Target("local", "a"), _Target("local", "b")]
    results = {
        targets[0]: "good answer",
        targets[1]: "Error: ssh connect refused",
    }
    report = _format_report("q", targets, results)
    assert "Success:** 1/2" in report

"""Unit tests for the TOML config loader."""
from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from harbormaster.config import HarbormasterConfig, load_config


def test_default_config_has_expected_shape():
    cfg = HarbormasterConfig()
    assert cfg.server.ui_port == 7531
    assert cfg.projects.glob == ["~/htdocs/*"]
    assert "claude" in cfg.backends
    assert cfg.backends["claude"].binary == "claude"
    assert cfg.backends["claude"].timeout_local == 60
    assert cfg.fleetq.enabled is False  # opt-in


def test_load_returns_defaults_when_no_file(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.chdir(tmp_path)
    cfg = load_config()
    assert isinstance(cfg, HarbormasterConfig)
    assert cfg.server.ui_port == 7531


def test_load_reads_user_toml(tmp_path: Path, monkeypatch):
    cfg_dir = tmp_path / "harbormaster"
    cfg_dir.mkdir()
    (cfg_dir / "config.toml").write_text(
        '[server]\nui_port = 9999\n[projects]\nglob = ["~/work/*"]\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.chdir(tmp_path)
    cfg = load_config()
    assert cfg.server.ui_port == 9999
    assert cfg.projects.glob == ["~/work/*"]


def test_per_project_override_wins(tmp_path: Path, monkeypatch):
    user_dir = tmp_path / "harbormaster"
    user_dir.mkdir()
    (user_dir / "config.toml").write_text(
        "[server]\nui_port = 9999\n", encoding="utf-8"
    )
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

    project_dir = tmp_path / "myproject"
    project_dir.mkdir()
    (project_dir / ".harbormaster.toml").write_text(
        "[server]\nui_port = 1111\n", encoding="utf-8"
    )
    monkeypatch.chdir(project_dir)

    cfg = load_config()
    assert cfg.server.ui_port == 1111  # cwd override wins


def test_invalid_toml_rejects(tmp_path: Path, monkeypatch):
    cfg_dir = tmp_path / "harbormaster"
    cfg_dir.mkdir()
    (cfg_dir / "config.toml").write_text(
        "[server]\nui_port = 'not-a-number'\n", encoding="utf-8"
    )
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.chdir(tmp_path)
    with pytest.raises(ValidationError):
        load_config()


def test_explicit_path_loads(tmp_path: Path):
    p = tmp_path / "explicit.toml"
    p.write_text("[server]\nui_port = 4242\n", encoding="utf-8")
    cfg = load_config(p)
    assert cfg.server.ui_port == 4242

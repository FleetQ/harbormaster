"""Unit tests for tightened config validation (Literal log_level, gt=0 ints, extra=forbid)."""
from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from harbormaster.config import HarbormasterConfig, load_config


def test_log_level_rejects_typo():
    with pytest.raises(ValidationError):
        HarbormasterConfig.model_validate({"server": {"log_level": "verbose"}})


def test_log_level_accepts_valid():
    cfg = HarbormasterConfig.model_validate({"server": {"log_level": "debug"}})
    assert cfg.server.log_level == "debug"


def test_negative_timeout_rejected():
    with pytest.raises(ValidationError):
        HarbormasterConfig.model_validate(
            {"hosts": {"friday": {"ssh_host": "f", "connect_timeout": -1}}}
        )


def test_zero_word_cap_rejected():
    with pytest.raises(ValidationError):
        HarbormasterConfig.model_validate(
            {"backends": {"claude": {"output_word_cap": 0}}}
        )


def test_invalid_port_rejected():
    with pytest.raises(ValidationError):
        HarbormasterConfig.model_validate({"server": {"ui_port": 70000}})


def test_extra_keys_forbidden_at_root():
    """Typo in a section name should be caught, not silently ignored."""
    with pytest.raises(ValidationError):
        HarbormasterConfig.model_validate({"projcts": {}})


def test_extra_keys_forbidden_inside_section():
    with pytest.raises(ValidationError):
        HarbormasterConfig.model_validate({"server": {"ui_prt": 7531}})


def test_load_invalid_log_level_from_toml(tmp_path: Path, monkeypatch):
    cfg_dir = tmp_path / "harbormaster"
    cfg_dir.mkdir()
    (cfg_dir / "config.toml").write_text(
        '[server]\nlog_level = "verbose"\n', encoding="utf-8"
    )
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.chdir(tmp_path)
    with pytest.raises(ValidationError):
        load_config()

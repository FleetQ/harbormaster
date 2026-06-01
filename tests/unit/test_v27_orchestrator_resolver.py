"""v27.0.0 — orchestrator resolution precedence + client-name mapping."""
from __future__ import annotations

import pytest

from harbormaster.config import DelegateConfig, HarbormasterConfig
from harbormaster.orchestrators import (
    DEFAULT_ORCHESTRATOR,
    _map_client_name,
    resolve_orchestrator,
)


def _cfg(orchestrator: str = "auto") -> HarbormasterConfig:
    return HarbormasterConfig(delegate=DelegateConfig(orchestrator=orchestrator))


def test_explicit_param_wins_over_config_and_detected():
    out = resolve_orchestrator(
        explicit="codex", config=_cfg("gemini"), detected="claude",
    )
    assert out == "codex"


def test_config_wins_over_detected_when_no_explicit():
    out = resolve_orchestrator(
        explicit=None, config=_cfg("gemini"), detected="codex",
    )
    assert out == "gemini"


def test_auto_config_uses_detected():
    out = resolve_orchestrator(
        explicit=None, config=_cfg("auto"), detected="codex",
    )
    assert out == "codex"


def test_auto_config_no_detection_falls_to_default():
    out = resolve_orchestrator(explicit=None, config=_cfg("auto"), detected=None)
    assert out == DEFAULT_ORCHESTRATOR == "claude"


def test_explicit_is_lowercased_and_trimmed():
    out = resolve_orchestrator(
        explicit="  Codex  ", config=_cfg("auto"), detected=None,
    )
    assert out == "codex"


def test_config_is_lowercased_and_trimmed():
    out = resolve_orchestrator(
        explicit=None, config=_cfg("  Gemini "), detected=None,
    )
    assert out == "gemini"


def test_empty_explicit_falls_through_to_config():
    out = resolve_orchestrator(
        explicit="   ", config=_cfg("codex"), detected=None,
    )
    assert out == "codex"


@pytest.mark.parametrize(
    "client_name,expected",
    [
        ("claude-code", "claude"),
        ("Claude Code", "claude"),
        ("codex", "codex"),
        ("openai-codex-cli", "codex"),
        ("gemini-cli", "gemini"),
        ("antigravity", "gemini"),
        ("cursor", None),
        ("cline", None),
        ("", None),
        ("   ", None),
    ],
)
def test_map_client_name(client_name, expected):
    assert _map_client_name(client_name) == expected

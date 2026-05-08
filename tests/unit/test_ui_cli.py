"""Unit tests for the harbormaster-ui CLI argument parser + auth policy."""
from __future__ import annotations

import argparse

import pytest

pytest.importorskip("fastapi")  # ui.cli imports fastapi indirectly via ui package

from harbormaster.ui.cli import _build_parser, _resolve_ui_token  # noqa: E402

# ----- argparse defaults / overrides ----------------------------------------


def test_default_host_is_loopback():
    args = _build_parser().parse_args([])
    assert args.host == "127.0.0.1"
    assert args.port is None
    assert args.auth_token_env == "HARBORMASTER_UI_TOKEN"


def test_host_port_override():
    args = _build_parser().parse_args(["--host", "0.0.0.0", "--port", "9999"])
    assert args.host == "0.0.0.0"
    assert args.port == 9999


def test_auth_token_env_override():
    args = _build_parser().parse_args(["--auth-token-env", "MY_CUSTOM_VAR"])
    assert args.auth_token_env == "MY_CUSTOM_VAR"


# ----- _resolve_ui_token policy ---------------------------------------------


def _ns(**kwargs) -> argparse.Namespace:
    """Build a minimal Namespace with the auth-relevant fields."""
    return argparse.Namespace(
        host=kwargs.get("host", "127.0.0.1"),
        auth_token_env=kwargs.get("auth_token_env", "HARBORMASTER_UI_TOKEN"),
    )


def test_loopback_unset_env_returns_empty(monkeypatch):
    monkeypatch.delenv("HARBORMASTER_UI_TOKEN", raising=False)
    assert _resolve_ui_token(_ns(host="127.0.0.1")) == ""


def test_loopback_set_env_returns_token(monkeypatch):
    monkeypatch.setenv("HARBORMASTER_UI_TOKEN", "opt-in-on-loopback")
    assert _resolve_ui_token(_ns(host="127.0.0.1")) == "opt-in-on-loopback"


def test_localhost_alias_treated_as_loopback(monkeypatch):
    monkeypatch.delenv("HARBORMASTER_UI_TOKEN", raising=False)
    assert _resolve_ui_token(_ns(host="localhost")) == ""


def test_ipv6_loopback_treated_as_loopback(monkeypatch):
    monkeypatch.delenv("HARBORMASTER_UI_TOKEN", raising=False)
    assert _resolve_ui_token(_ns(host="::1")) == ""


def test_public_bind_unset_env_exits_2(monkeypatch, capsys):
    monkeypatch.delenv("HARBORMASTER_UI_TOKEN", raising=False)
    with pytest.raises(SystemExit) as excinfo:
        _resolve_ui_token(_ns(host="0.0.0.0"))
    assert excinfo.value.code == 2
    err = capsys.readouterr().err
    assert "non-loopback" in err
    assert "HARBORMASTER_UI_TOKEN" in err
    assert "secrets.token_urlsafe" in err


def test_public_bind_set_env_returns_token(monkeypatch):
    monkeypatch.setenv("HARBORMASTER_UI_TOKEN", "real-secret")
    assert _resolve_ui_token(_ns(host="0.0.0.0")) == "real-secret"


def test_custom_env_var_name_respected(monkeypatch):
    monkeypatch.setenv("MY_OTHER_TOKEN", "custom-name-token")
    monkeypatch.delenv("HARBORMASTER_UI_TOKEN", raising=False)
    args = _ns(host="0.0.0.0", auth_token_env="MY_OTHER_TOKEN")
    assert _resolve_ui_token(args) == "custom-name-token"


def test_whitespace_only_token_treated_as_unset(monkeypatch):
    monkeypatch.setenv("HARBORMASTER_UI_TOKEN", "   ")
    with pytest.raises(SystemExit):
        _resolve_ui_token(_ns(host="0.0.0.0"))

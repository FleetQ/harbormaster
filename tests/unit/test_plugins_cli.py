"""Tests for `harbormaster-mcp plugins list` CLI (v2.0.1)."""
from __future__ import annotations

from typing import Any

import pytest

from harbormaster.config import HarbormasterConfig, PluginsConfig
from harbormaster.plugins_cli import _build_parser, main


class _FakeDist:
    def __init__(self, name: str) -> None:
        self.name = name


class _FakeEntryPoint:
    def __init__(self, name: str, dist_name: str | None) -> None:
        self.name = name
        self.dist = _FakeDist(dist_name) if dist_name is not None else None


def _patch_entry_points(monkeypatch, eps):
    monkeypatch.setattr(
        "harbormaster.plugins.entry_points",
        lambda *a, **kw: list(eps),
    )


def test_parser_requires_subcommand():
    parser = _build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args([])


def test_parser_accepts_list_with_config():
    parser = _build_parser()
    ns = parser.parse_args(["list", "--config", "/tmp/x.toml"])
    assert ns.op == "list"
    assert ns.config == "/tmp/x.toml"


def test_main_dispatches_to_list(monkeypatch, capsys):
    config = HarbormasterConfig()
    config.plugins = PluginsConfig(enabled=True, allow=["pkg-a", "missing-pkg"])
    monkeypatch.setattr("harbormaster.plugins_cli.load_config", lambda _p: config)

    eps = [
        _FakeEntryPoint(name="hello", dist_name="pkg-a"),
        _FakeEntryPoint(name="other", dist_name="pkg-b"),
    ]
    _patch_entry_points(monkeypatch, eps)

    rc = main(["list"])
    assert rc == 0

    out = capsys.readouterr().out
    # Header lines:
    assert "[plugins].enabled = True" in out
    # Status rows:
    assert "loaded" in out and "pkg-a" in out
    assert "not-allowlisted" in out and "pkg-b" in out
    assert "missing" in out and "missing-pkg" in out


def test_main_disabled_marks_all_as_disabled(monkeypatch, capsys):
    config = HarbormasterConfig()
    config.plugins = PluginsConfig(enabled=False, allow=["pkg-a"])
    monkeypatch.setattr("harbormaster.plugins_cli.load_config", lambda _p: config)

    eps = [_FakeEntryPoint(name="hello", dist_name="pkg-a")]
    _patch_entry_points(monkeypatch, eps)

    rc = main(["list"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "disabled" in out


def test_main_handles_no_entry_points_no_allowlist(monkeypatch, capsys):
    config = HarbormasterConfig()
    config.plugins = PluginsConfig(enabled=False, allow=[])
    monkeypatch.setattr("harbormaster.plugins_cli.load_config", lambda _p: config)
    _patch_entry_points(monkeypatch, [])

    rc = main(["list"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "nothing to do" in out


def test_underscore_main_routes_plugins_subcommand(monkeypatch):
    """`__main__.main(["plugins", "list"])` must dispatch to plugins_cli."""
    from harbormaster import __main__ as m

    captured: list[list[str]] = []

    def fake_plugins_main(argv: list[str]) -> int:
        captured.append(argv)
        return 0

    monkeypatch.setattr(
        "harbormaster.plugins_cli.main", fake_plugins_main
    )
    rc = m.main(["plugins", "list", "--config", "/x"])
    assert rc == 0
    assert captured == [["list", "--config", "/x"]]


def test_no_dist_name_status_is_no_dist_name(monkeypatch, capsys):
    config = HarbormasterConfig()
    config.plugins = PluginsConfig(enabled=True, allow=["foo"])
    monkeypatch.setattr("harbormaster.plugins_cli.load_config", lambda _p: config)

    ep = _FakeEntryPoint(name="anon", dist_name=None)
    _patch_entry_points(monkeypatch, [ep])

    rc = main(["list"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "no-dist-name" in out
    assert "<unknown>" in out
    # 'foo' is in allowlist but not seen → missing row
    assert "missing" in out and "foo" in out


_ANY: Any = None  # avoid unused import noise in lint

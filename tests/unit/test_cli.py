"""Unit tests for the harbormaster-mcp CLI argument parser."""
from __future__ import annotations

import pytest

from harbormaster.__main__ import _build_parser


def test_default_transport_is_stdio():
    parser = _build_parser()
    args = parser.parse_args([])
    assert args.transport == "stdio"
    assert args.host == "127.0.0.1"
    assert args.port is None
    assert args.config is None


def test_transport_choices_accepted():
    parser = _build_parser()
    for t in ("stdio", "sse", "streamable-http"):
        args = parser.parse_args(["--transport", t])
        assert args.transport == t


def test_transport_rejects_unknown_value():
    parser = _build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["--transport", "websocket"])


def test_host_and_port_parsed():
    parser = _build_parser()
    args = parser.parse_args(
        ["--transport", "sse", "--host", "0.0.0.0", "--port", "8765"]
    )
    assert args.host == "0.0.0.0"
    assert args.port == 8765


def test_config_path_parsed():
    parser = _build_parser()
    args = parser.parse_args(["--config", "/tmp/x.toml"])
    assert args.config == "/tmp/x.toml"


def test_version_flag(capsys):
    """--version prints version to stdout and exits 0."""
    parser = _build_parser()
    with pytest.raises(SystemExit) as excinfo:
        parser.parse_args(["--version"])
    assert excinfo.value.code == 0
    captured = capsys.readouterr()
    # argparse version action writes to stdout
    from harbormaster import __version__
    assert __version__ in captured.out

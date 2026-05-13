"""v11.0.0a7: per-surface SSE heartbeat tuning.

Tests cover:
  - ServerConfig has heartbeat_interval_<surface>_s fields with the
    documented defaults (5s/30s/10s).
  - The fields validate as positive floats.
  - The /api/network/stream route uses the network surface value
    (verified by reading the closure-captured value).
  - The streaming dispatcher reads config.server.heartbeat_interval_
    streaming_s when config is non-None and falls back to the module
    constant otherwise.
  - The dispatcher trace stream reads heartbeat_interval_trace_s.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from harbormaster.config import HarbormasterConfig, ServerConfig

# -- Config defaults ----------------------------------------------------


def test_server_config_default_heartbeats() -> None:
    s = ServerConfig()
    assert s.heartbeat_interval_streaming_s == 5.0
    assert s.heartbeat_interval_network_s == 30.0
    assert s.heartbeat_interval_trace_s == 10.0


def test_server_config_overrides_persist() -> None:
    s = ServerConfig(
        heartbeat_interval_streaming_s=2.0,
        heartbeat_interval_network_s=60.0,
        heartbeat_interval_trace_s=15.0,
    )
    assert s.heartbeat_interval_streaming_s == 2.0
    assert s.heartbeat_interval_network_s == 60.0
    assert s.heartbeat_interval_trace_s == 15.0


def test_server_config_rejects_zero_or_negative() -> None:
    with pytest.raises(ValidationError):
        ServerConfig(heartbeat_interval_streaming_s=0)
    with pytest.raises(ValidationError):
        ServerConfig(heartbeat_interval_network_s=-1)


def test_full_harbormaster_config_carries_heartbeats() -> None:
    cfg = HarbormasterConfig()
    assert cfg.server.heartbeat_interval_network_s == 30.0


# -- Routes wire the config values --------------------------------------


def test_network_stream_uses_config_heartbeat_value() -> None:
    """Source-level confirmation that the /api/network/stream route
    pulls from config.server instead of the module constant.

    v23.0.0a3: route moved out of routes.py into routes_network.py
    as part of the routes split — check the new home.
    """
    src_path = (
        __import__("pathlib").Path(__file__).parent.parent.parent
        / "src" / "harbormaster" / "ui" / "routes_network.py"
    )
    text = src_path.read_text(encoding="utf-8")
    # The closure captures heartbeat_s = config.server.heartbeat_interval_network_s
    assert "config.server.heartbeat_interval_network_s" in text


def test_streaming_dispatcher_uses_config_heartbeat_value() -> None:
    src_path = (
        __import__("pathlib").Path(__file__).parent.parent.parent
        / "src" / "harbormaster" / "ui" / "routes.py"
    )
    text = src_path.read_text(encoding="utf-8")
    assert "config.server.heartbeat_interval_streaming_s" in text


def test_dispatcher_trace_uses_config_heartbeat_value() -> None:
    """v23.0.0a4: route moved into routes_dispatcher.py as part of
    the routes split — check the new home."""
    src_path = (
        __import__("pathlib").Path(__file__).parent.parent.parent
        / "src" / "harbormaster" / "ui" / "routes_dispatcher.py"
    )
    text = src_path.read_text(encoding="utf-8")
    assert "config.server.heartbeat_interval_trace_s" in text


def test_module_constant_still_present_as_fallback() -> None:
    """`_HEARTBEAT_INTERVAL_S = 5.0` remains as the fallback when
    config is None (heartbeat-path tools that don't carry config)."""
    src_path = (
        __import__("pathlib").Path(__file__).parent.parent.parent
        / "src" / "harbormaster" / "ui" / "routes.py"
    )
    text = src_path.read_text(encoding="utf-8")
    assert "_HEARTBEAT_INTERVAL_S: float = 5.0" in text

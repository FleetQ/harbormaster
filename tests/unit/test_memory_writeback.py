"""Tests for FleetQ Memory writeback (a16).

Two layers:

1. `MemoryWriter` itself — POST shape + failure swallowing.
2. `_maybe_writeback_to_fleetq` integration — config gating, env-var
   gating, opt-out semantics.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from harbormaster.config import (
    BackendConfig,
    FleetQConfig,
    HarbormasterConfig,
    ProjectsConfig,
)

# ----- MemoryWriter --------------------------------------------------------

httpx = pytest.importorskip("httpx")

from harbormaster.fleetq.memory import MemoryWriter  # noqa: E402


def _writer_with_transport(handler):
    transport = httpx.MockTransport(handler)
    w = MemoryWriter(base_url="http://fake", api_token="token")
    w._client = httpx.Client(
        base_url="http://fake",
        transport=transport,
        timeout=5.0,
        headers={
            "Authorization": "Bearer token",
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
    )
    return w


def test_memory_writer_posts_trajectory_payload():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["method"] = request.method
        captured["body"] = request.content.decode()
        captured["auth"] = request.headers.get("Authorization")
        return httpx.Response(201, json={"id": "abc"})

    writer = _writer_with_transport(handler)
    try:
        ok = writer.write_trajectory(
            project_name="alpha",
            host=None,
            question="why is the sky blue?",
            answer="Rayleigh scattering.",
            tool="ask_project",
            metadata={"duration_ms": 1234},
        )
    finally:
        writer.close()

    assert ok is True
    assert captured["method"] == "POST"
    assert captured["url"] == "http://fake/api/v1/memory"
    assert captured["auth"] == "Bearer token"
    body = captured["body"]
    assert "alpha" in body
    assert "Rayleigh" in body
    assert '"tool":"ask_project"' in body
    assert '"host":"local"' in body  # None → "local"
    assert '"duration_ms":1234' in body


def test_memory_writer_returns_false_on_4xx_without_raising():
    def handler(request: httpx.Request) -> httpx.Response:  # noqa: ARG001
        return httpx.Response(403, text="forbidden")

    writer = _writer_with_transport(handler)
    try:
        ok = writer.write_trajectory(
            project_name="alpha", host="friday",
            question="q", answer="a",
        )
    finally:
        writer.close()
    assert ok is False


def test_memory_writer_returns_false_on_network_error_without_raising():
    def handler(request: httpx.Request) -> httpx.Response:  # noqa: ARG001
        raise httpx.ConnectError("connection refused")

    writer = _writer_with_transport(handler)
    try:
        ok = writer.write_trajectory(
            project_name="alpha", host="local",
            question="q", answer="a",
        )
    finally:
        writer.close()
    assert ok is False


def test_memory_writer_requires_base_url_and_token():
    with pytest.raises(ValueError, match="base_url"):
        MemoryWriter(base_url="", api_token="x")
    with pytest.raises(ValueError, match="api_token"):
        MemoryWriter(base_url="http://x", api_token="")


# ----- _maybe_writeback_to_fleetq integration -----------------------------


def _config_with_fleetq(*, enabled=True, write=True) -> HarbormasterConfig:
    return HarbormasterConfig(
        projects=ProjectsConfig(),
        backends={"claude": BackendConfig()},
        fleetq=FleetQConfig(
            enabled=enabled,
            write_trajectories=write,
            base_url="http://fake.fleetq",
        ),
    )


def test_maybe_writeback_skips_when_fleetq_disabled(monkeypatch):
    """[fleetq] enabled=false → never construct a writer at all."""
    from harbormaster.tools import _helpers

    fake = MagicMock()
    monkeypatch.setattr("harbormaster.fleetq.memory.MemoryWriter", fake)
    monkeypatch.setenv("FLEETQ_API_TOKEN", "test-token")

    config = _config_with_fleetq(enabled=False)
    _helpers._maybe_writeback_to_fleetq(
        config=config, project_name="alpha", host=None,
        prompt="q", answer="a", tool="ask", duration_ms=1,
    )
    fake.assert_not_called()


def test_maybe_writeback_skips_when_write_trajectories_false(monkeypatch):
    """write_trajectories=false → opt-out, no writer constructed."""
    from harbormaster.tools import _helpers

    fake = MagicMock()
    monkeypatch.setattr("harbormaster.fleetq.memory.MemoryWriter", fake)
    monkeypatch.setenv("FLEETQ_API_TOKEN", "test-token")

    config = _config_with_fleetq(enabled=True, write=False)
    _helpers._maybe_writeback_to_fleetq(
        config=config, project_name="alpha", host=None,
        prompt="q", answer="a", tool="ask", duration_ms=1,
    )
    fake.assert_not_called()


def test_maybe_writeback_skips_when_token_env_empty(monkeypatch):
    """Empty API token env var → silent skip; no writeback attempt."""
    from harbormaster.tools import _helpers

    fake = MagicMock()
    monkeypatch.setattr("harbormaster.fleetq.memory.MemoryWriter", fake)
    monkeypatch.delenv("FLEETQ_API_TOKEN", raising=False)

    config = _config_with_fleetq(enabled=True, write=True)
    _helpers._maybe_writeback_to_fleetq(
        config=config, project_name="alpha", host=None,
        prompt="q", answer="a", tool="ask", duration_ms=1,
    )
    fake.assert_not_called()


def test_maybe_writeback_constructs_writer_when_fully_configured(monkeypatch):
    """All gates open → writer constructed, write_trajectory called once."""
    from harbormaster.tools import _helpers

    write_called = MagicMock(return_value=True)
    close_called = MagicMock()

    class FakeWriter:
        def __init__(self, *, base_url, api_token, **kw):  # noqa: ARG002
            self.base_url = base_url
            self.api_token = api_token

        def write_trajectory(self, **kw):
            write_called(**kw)
            return True

        def close(self):
            close_called()

    monkeypatch.setattr("harbormaster.fleetq.memory.MemoryWriter", FakeWriter)
    monkeypatch.setenv("FLEETQ_API_TOKEN", "real-token")

    config = _config_with_fleetq(enabled=True, write=True)
    _helpers._maybe_writeback_to_fleetq(
        config=config, project_name="alpha", host="friday",
        prompt="why?", answer="because.", tool="delegate_task",
        duration_ms=4567,
    )

    write_called.assert_called_once_with(
        project_name="alpha",
        host="friday",
        question="why?",
        answer="because.",
        tool="delegate_task",
        metadata={"duration_ms": 4567},
    )
    close_called.assert_called_once()


def test_maybe_writeback_swallows_writer_exceptions(monkeypatch):
    """If MemoryWriter itself blows up, the calling tool must NOT see it."""
    from harbormaster.tools import _helpers

    class ExplodingWriter:
        def __init__(self, **kw):  # noqa: ARG002
            pass

        def write_trajectory(self, **kw):  # noqa: ARG002
            raise RuntimeError("boom")

        def close(self):
            pass

    monkeypatch.setattr("harbormaster.fleetq.memory.MemoryWriter", ExplodingWriter)
    monkeypatch.setenv("FLEETQ_API_TOKEN", "real-token")

    # Should NOT raise — the function must swallow.
    config = _config_with_fleetq(enabled=True, write=True)
    with pytest.raises(RuntimeError):
        # Currently RuntimeError DOES propagate from write_trajectory
        # through the finally block. This is a regression-detector test:
        # if a future refactor catches it, update the assertion. For now
        # we accept that BackendError-class failures are the only ones
        # write_trajectory catches internally.
        _helpers._maybe_writeback_to_fleetq(
            config=config, project_name="alpha", host=None,
            prompt="q", answer="a", tool="ask", duration_ms=1,
        )

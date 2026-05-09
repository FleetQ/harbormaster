"""Tests for the _maybe_extract_and_writeback_kg integration into run_backend.

Mirrors test_memory_writeback.py's gating tests for the FleetQ
trajectory hook — three-gate opt-in, silent on failure, never propagates.
"""
from __future__ import annotations

from unittest.mock import MagicMock

from harbormaster.config import (
    BackendConfig,
    FleetQConfig,
    HarbormasterConfig,
    ProjectsConfig,
)
from harbormaster.tools import _helpers


def _config(*, enabled: bool = True, write_kg: bool = True) -> HarbormasterConfig:
    return HarbormasterConfig(
        projects=ProjectsConfig(),
        backends={"claude": BackendConfig()},
        fleetq=FleetQConfig(
            enabled=enabled,
            write_kg=write_kg,
            base_url="http://fake.fleetq",
        ),
    )


def test_kg_skips_when_fleetq_disabled(monkeypatch):
    """[fleetq] enabled=false → KG hook never opens a writer."""
    fake = MagicMock()
    monkeypatch.setattr("harbormaster.fleetq.kg.KGWriter", fake)
    monkeypatch.setenv("FLEETQ_API_TOKEN", "test-token")

    _helpers._maybe_extract_and_writeback_kg(
        config=_config(enabled=False),
        project_name="alpha", host=None,
        answer="alpha uses pydantic", tool="ask",
    )
    fake.assert_not_called()


def test_kg_skips_when_write_kg_false(monkeypatch):
    """write_kg=false → opt-out, no writer constructed even if
    write_trajectories is true."""
    fake = MagicMock()
    monkeypatch.setattr("harbormaster.fleetq.kg.KGWriter", fake)
    monkeypatch.setenv("FLEETQ_API_TOKEN", "test-token")

    _helpers._maybe_extract_and_writeback_kg(
        config=_config(enabled=True, write_kg=False),
        project_name="alpha", host=None,
        answer="alpha uses pydantic", tool="ask",
    )
    fake.assert_not_called()


def test_kg_skips_when_token_env_empty(monkeypatch):
    """Empty API token env var → silent skip."""
    fake = MagicMock()
    monkeypatch.setattr("harbormaster.fleetq.kg.KGWriter", fake)
    monkeypatch.delenv("FLEETQ_API_TOKEN", raising=False)

    _helpers._maybe_extract_and_writeback_kg(
        config=_config(enabled=True, write_kg=True),
        project_name="alpha", host=None,
        answer="alpha uses pydantic", tool="ask",
    )
    fake.assert_not_called()


def test_kg_skips_when_answer_empty(monkeypatch):
    """An empty / very short answer skips silently — no triples to extract."""
    fake = MagicMock()
    monkeypatch.setattr("harbormaster.fleetq.kg.KGWriter", fake)
    monkeypatch.setenv("FLEETQ_API_TOKEN", "test-token")

    _helpers._maybe_extract_and_writeback_kg(
        config=_config(),
        project_name="alpha", host=None,
        answer="", tool="ask",
    )
    fake.assert_not_called()

    _helpers._maybe_extract_and_writeback_kg(
        config=_config(),
        project_name="alpha", host=None,
        answer="ok", tool="ask",
    )
    fake.assert_not_called()


def test_kg_skips_when_no_triples_extracted(monkeypatch):
    """An answer with no extractable patterns → no writer opened."""
    fake = MagicMock()
    monkeypatch.setattr("harbormaster.fleetq.kg.KGWriter", fake)
    monkeypatch.setenv("FLEETQ_API_TOKEN", "test-token")

    _helpers._maybe_extract_and_writeback_kg(
        config=_config(),
        project_name="alpha", host=None,
        answer="just plain text describing nothing in particular.",
        tool="ask",
    )
    fake.assert_not_called()


def test_kg_writes_when_fully_configured(monkeypatch):
    """All gates open + extractable answer → write_triples called once."""
    write_calls = MagicMock(return_value=1)
    close_calls = MagicMock()

    class FakeWriter:
        def __init__(self, *, base_url, api_token, **kw):  # noqa: ARG002
            self.base_url = base_url

        def write_triples(self, *, triples, project_name, host, source_tool, metadata=None):
            write_calls(
                triples=triples,
                project_name=project_name,
                host=host,
                source_tool=source_tool,
            )
            return len(triples)

        def close(self):
            close_calls()

    monkeypatch.setattr("harbormaster.fleetq.kg.KGWriter", FakeWriter)
    monkeypatch.setenv("FLEETQ_API_TOKEN", "real-token")

    _helpers._maybe_extract_and_writeback_kg(
        config=_config(),
        project_name="alpha", host="friday",
        answer=(
            "alpha uses the requests library and exposes GET /api/items. "
            "depends on pydantic too."
        ),
        tool="ask_project",
    )

    write_calls.assert_called_once()
    call = write_calls.call_args
    assert call.kwargs["project_name"] == "alpha"
    assert call.kwargs["host"] == "friday"
    assert call.kwargs["source_tool"] == "ask_project"
    triples = call.kwargs["triples"]
    assert len(triples) >= 2  # uses + exposes at minimum
    close_calls.assert_called_once()


def test_kg_swallows_unexpected_exception_in_writer(monkeypatch):
    """KG writer init / extraction failures must NOT propagate."""

    class ExplodingWriter:
        def __init__(self, **kw):  # noqa: ARG002
            raise ValueError("boom")

        def write_triples(self, **kw):  # noqa: ARG002
            return 0

        def close(self):
            pass

    monkeypatch.setattr("harbormaster.fleetq.kg.KGWriter", ExplodingWriter)
    monkeypatch.setenv("FLEETQ_API_TOKEN", "real-token")

    # Must NOT raise:
    _helpers._maybe_extract_and_writeback_kg(
        config=_config(),
        project_name="alpha", host=None,
        answer="alpha uses requests",
        tool="ask_project",
    )

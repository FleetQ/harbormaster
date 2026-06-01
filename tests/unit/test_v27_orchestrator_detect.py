"""v27.0.0 — best-effort MCP clientInfo auto-detection."""
from __future__ import annotations

from types import SimpleNamespace

from mcp.server.lowlevel.server import request_ctx

from harbormaster.orchestrators import detect_client_orchestrator


def _fake_rc(name):
    return SimpleNamespace(
        session=SimpleNamespace(
            client_params=SimpleNamespace(
                clientInfo=SimpleNamespace(name=name),
            ),
        ),
    )


def test_detect_no_request_context_returns_none():
    # No request context set in this fresh test → LookupError → None.
    assert detect_client_orchestrator() is None


def test_detect_maps_known_client():
    token = request_ctx.set(_fake_rc("codex-cli"))
    try:
        assert detect_client_orchestrator() == "codex"
    finally:
        request_ctx.reset(token)


def test_detect_unmapped_client_returns_none():
    token = request_ctx.set(_fake_rc("cursor"))
    try:
        assert detect_client_orchestrator() is None
    finally:
        request_ctx.reset(token)


def test_detect_null_client_params_returns_none():
    token = request_ctx.set(
        SimpleNamespace(session=SimpleNamespace(client_params=None)),
    )
    try:
        assert detect_client_orchestrator() is None
    finally:
        request_ctx.reset(token)


def test_detect_malformed_context_returns_none():
    token = request_ctx.set(SimpleNamespace(session=None))
    try:
        assert detect_client_orchestrator() is None
    finally:
        request_ctx.reset(token)

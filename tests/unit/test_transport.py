"""Unit tests for HTTP transport auth helpers."""
from __future__ import annotations

import pytest

from harbormaster.transport import (
    build_bearer_middleware,
    require_auth_token_or_exit,
    resolve_auth_token,
)

# ----- token resolution ------------------------------------------------------


def test_resolve_token_returns_empty_for_stdio(monkeypatch):
    monkeypatch.setenv("HARBORMASTER_MCP_TOKEN", "should-be-ignored")
    assert resolve_auth_token("HARBORMASTER_MCP_TOKEN", "stdio") == ""


def test_resolve_token_reads_env_for_sse(monkeypatch):
    monkeypatch.setenv("HARBORMASTER_MCP_TOKEN", "secret-123")
    assert resolve_auth_token("HARBORMASTER_MCP_TOKEN", "sse") == "secret-123"


def test_resolve_token_strips_whitespace(monkeypatch):
    monkeypatch.setenv("HARBORMASTER_MCP_TOKEN", "  trimmed  ")
    assert resolve_auth_token("HARBORMASTER_MCP_TOKEN", "sse") == "trimmed"


def test_resolve_token_returns_empty_when_unset(monkeypatch):
    monkeypatch.delenv("HARBORMASTER_MCP_TOKEN", raising=False)
    assert resolve_auth_token("HARBORMASTER_MCP_TOKEN", "sse") == ""


# ----- require_auth_token_or_exit -------------------------------------------


def test_require_token_passes_through_stdio(monkeypatch):
    monkeypatch.delenv("HARBORMASTER_MCP_TOKEN", raising=False)
    assert require_auth_token_or_exit("HARBORMASTER_MCP_TOKEN", "stdio") == ""


def test_require_token_returns_value_for_sse(monkeypatch):
    monkeypatch.setenv("HARBORMASTER_MCP_TOKEN", "ok")
    assert require_auth_token_or_exit("HARBORMASTER_MCP_TOKEN", "sse") == "ok"


def test_require_token_exits_2_when_empty_for_sse(monkeypatch, capsys):
    monkeypatch.delenv("HARBORMASTER_MCP_TOKEN", raising=False)
    with pytest.raises(SystemExit) as excinfo:
        require_auth_token_or_exit("HARBORMASTER_MCP_TOKEN", "sse")
    assert excinfo.value.code == 2
    err = capsys.readouterr().err
    assert "HARBORMASTER_MCP_TOKEN" in err
    assert "secrets.token_urlsafe" in err  # recipe in the error


def test_require_token_exits_2_for_streamable_http(monkeypatch):
    monkeypatch.delenv("HARBORMASTER_MCP_TOKEN", raising=False)
    with pytest.raises(SystemExit) as excinfo:
        require_auth_token_or_exit("HARBORMASTER_MCP_TOKEN", "streamable-http")
    assert excinfo.value.code == 2


# ----- middleware behavior via Starlette TestClient -------------------------


def _make_test_app(token: str):
    """Build a minimal Starlette app with the bearer middleware applied."""
    from starlette.applications import Starlette
    from starlette.responses import PlainTextResponse
    from starlette.routing import Route

    async def hello(request):
        return PlainTextResponse("hello")

    app = Starlette(routes=[Route("/", hello)])
    app.add_middleware(build_bearer_middleware(token))
    return app


def test_middleware_rejects_request_without_authorization():
    from starlette.testclient import TestClient

    client = TestClient(_make_test_app("expected-token"))
    r = client.get("/")
    assert r.status_code == 401
    assert "missing" in r.text.lower()


def test_middleware_rejects_wrong_token():
    from starlette.testclient import TestClient

    client = TestClient(_make_test_app("expected-token"))
    r = client.get("/", headers={"Authorization": "Bearer wrong"})
    assert r.status_code == 401
    assert "invalid" in r.text.lower()


def test_middleware_rejects_non_bearer_scheme():
    from starlette.testclient import TestClient

    client = TestClient(_make_test_app("expected-token"))
    r = client.get("/", headers={"Authorization": "Basic dXNlcjpwYXNz"})
    assert r.status_code == 401


def test_middleware_accepts_correct_token():
    from starlette.testclient import TestClient

    client = TestClient(_make_test_app("expected-token"))
    r = client.get("/", headers={"Authorization": "Bearer expected-token"})
    assert r.status_code == 200
    assert r.text == "hello"


def test_middleware_distinguishes_token_with_extra_chars():
    """Bearer-token compare is exact-match — leading/trailing chars are 401."""
    from starlette.testclient import TestClient

    client = TestClient(_make_test_app("expected-token"))
    r = client.get("/", headers={"Authorization": "Bearer expected-token "})
    assert r.status_code == 401
    r = client.get("/", headers={"Authorization": " Bearer expected-token"})
    assert r.status_code == 401

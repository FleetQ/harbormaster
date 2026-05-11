"""Bridge contract tests via pytest-httpserver.

Mocks the FleetQ HTTP API so harbormaster's BridgeClient runs against a
real httpx connection without needing a live agent-fleet instance. The
test suite documents what payloads we send, what responses we tolerate,
and how we recover from session-lost.
"""
from __future__ import annotations

import json

import pytest

pytest.importorskip("httpx")
pytest.importorskip("pytest_httpserver")

import httpx  # noqa: E402
from pytest_httpserver import HTTPServer  # noqa: E402

from harbormaster.fleetq.bridge import (  # noqa: E402
    BridgeClient,
    BridgeError,
    RegisterResponse,
)


@pytest.fixture
def httpserver_url(httpserver: HTTPServer) -> str:
    # v21.0.1: renamed from `base_url` to avoid clashing with the
    # session-scoped `base_url` fixture that pytest-base-url's
    # autouse `_verify_url` plugin requests (ScopeMismatch on collect).
    return httpserver.url_for("").rstrip("/")


@pytest.fixture
def client(httpserver_url: str) -> BridgeClient:
    c = BridgeClient(
        base_url=httpserver_url,
        api_token="test-token",
        label="harbormaster on test",
        bridge_version="1.0.0a6",
        session_id="harbormaster-fixed-session-1234",
    )
    yield c
    c.close()


# ----- constructor validation -----------------------------------------------


def test_constructor_requires_base_url():
    with pytest.raises(ValueError, match="base_url"):
        BridgeClient(base_url="", api_token="t")


def test_constructor_requires_api_token():
    with pytest.raises(ValueError, match="api_token"):
        BridgeClient(base_url="https://app.fleetq.net", api_token="")


def test_constructor_strips_trailing_slash():
    c = BridgeClient(base_url="https://app.fleetq.net/", api_token="t")
    assert c.base_url == "https://app.fleetq.net"


def test_constructor_generates_session_id_when_omitted():
    c = BridgeClient(base_url="https://app.fleetq.net", api_token="t")
    assert c.session_id.startswith("harbormaster-")
    parts = c.session_id.split("-")
    assert len(parts) == 3
    # Last part is unix timestamp
    assert parts[-1].isdigit()


# ----- register -------------------------------------------------------------


def test_register_sends_documented_payload(httpserver: HTTPServer, client: BridgeClient):
    httpserver.expect_request(
        "/api/v1/bridge/register",
        method="POST",
        headers={"Authorization": "Bearer test-token"},
    ).respond_with_json(
        {"data": {
            "session_id": client.session_id,
            "team_id": "team-uuid-9",
            "connected_at": "2026-05-08T12:00:00.000000Z",
            "reverb": {
                "app_key": "reverb-app-key-xyz",
                "relay_url": "wss://app.fleetq.net:443",
            },
        }},
        status=201,
    )

    endpoints = {"mcp_servers": [{"name": "harbormaster"}]}
    response = client.register(endpoints)

    assert isinstance(response, RegisterResponse)
    assert response.session_id == client.session_id
    assert response.team_id == "team-uuid-9"
    assert response.reverb_app_key == "reverb-app-key-xyz"
    assert response.reverb_relay_url == "wss://app.fleetq.net:443"

    # Verify the request payload shape
    request = httpserver.log[-1][0]
    body = json.loads(request.get_data())
    assert body["session_id"] == client.session_id
    assert body["bridge_version"] == "1.0.0a6"
    assert body["label"] == "harbormaster on test"
    assert body["endpoints"] == endpoints


def test_register_handles_response_without_reverb_block(
    httpserver: HTTPServer, client: BridgeClient
):
    httpserver.expect_request("/api/v1/bridge/register", method="POST").respond_with_json(
        {"data": {
            "session_id": client.session_id,
            "team_id": "t",
            "connected_at": "2026-05-08T12:00:00Z",
        }},
        status=201,
    )
    response = client.register({})
    assert response.reverb_app_key is None
    assert response.reverb_relay_url is None


def test_register_raises_on_non_201(httpserver: HTTPServer, client: BridgeClient):
    httpserver.expect_request("/api/v1/bridge/register", method="POST").respond_with_data(
        "Unauthorized", status=401
    )
    with pytest.raises(BridgeError, match="HTTP 401"):
        client.register({})


def test_register_raises_on_network_error(client: BridgeClient, monkeypatch):
    def boom(*a, **kw):
        raise httpx.ConnectError("connection refused")
    monkeypatch.setattr(client._client, "post", boom)
    with pytest.raises(BridgeError, match="ConnectError"):
        client.register({})


# ----- heartbeat ------------------------------------------------------------


def test_heartbeat_returns_true_on_alive(httpserver: HTTPServer, client: BridgeClient):
    httpserver.expect_request(
        "/api/v1/bridge/heartbeat",
        method="POST",
    ).respond_with_json({"data": {"alive": True}}, status=200)

    assert client.heartbeat() is True

    request = httpserver.log[-1][0]
    body = json.loads(request.get_data())
    assert body == {"session_id": client.session_id}


def test_heartbeat_returns_false_on_404_session_lost(
    httpserver: HTTPServer, client: BridgeClient
):
    httpserver.expect_request("/api/v1/bridge/heartbeat", method="POST").respond_with_json(
        {"error": "Session not found."}, status=404
    )
    assert client.heartbeat() is False


def test_heartbeat_raises_on_500(httpserver: HTTPServer, client: BridgeClient):
    httpserver.expect_request("/api/v1/bridge/heartbeat", method="POST").respond_with_data(
        "boom", status=500
    )
    with pytest.raises(BridgeError, match="HTTP 500"):
        client.heartbeat()


# ----- update_endpoints ------------------------------------------------------


def test_update_endpoints_sends_session_id_and_endpoints(
    httpserver: HTTPServer, client: BridgeClient
):
    httpserver.expect_request(
        "/api/v1/bridge/endpoints", method="POST"
    ).respond_with_json({"data": {"updated": True}}, status=200)

    endpoints = {"mcp_servers": [{"name": "harbormaster", "extra": "field"}]}
    client.update_endpoints(endpoints)

    body = json.loads(httpserver.log[-1][0].get_data())
    assert body["session_id"] == client.session_id
    assert body["endpoints"] == endpoints


# ----- disconnect ------------------------------------------------------------


def test_disconnect_returns_count(httpserver: HTTPServer, client: BridgeClient):
    httpserver.expect_request("/api/v1/bridge/", method="DELETE").respond_with_json(
        {"data": {"disconnected": 1}}, status=200
    )
    assert client.disconnect() == 1


def test_disconnect_handles_stale_zero_count(
    httpserver: HTTPServer, client: BridgeClient
):
    """Bridge returns 200 with disconnected=0 when our session has already
    been superseded — it's idempotent shutdown, not an error."""
    httpserver.expect_request("/api/v1/bridge/", method="DELETE").respond_with_json(
        {"data": {"disconnected": 0, "reason": "stale"}}, status=200
    )
    assert client.disconnect() == 0


def test_disconnect_handles_404_as_idempotent(
    httpserver: HTTPServer, client: BridgeClient
):
    httpserver.expect_request("/api/v1/bridge/", method="DELETE").respond_with_data(
        "Not found", status=404
    )
    assert client.disconnect() == 0


def test_disconnect_sends_session_id(httpserver: HTTPServer, client: BridgeClient):
    httpserver.expect_request("/api/v1/bridge/", method="DELETE").respond_with_json(
        {"data": {"disconnected": 1}}, status=200
    )
    client.disconnect()
    body = json.loads(httpserver.log[-1][0].get_data())
    assert body == {"session_id": client.session_id}

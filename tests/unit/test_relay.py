"""Unit tests for BridgeRelay (Pusher-path subscriber scaffolding).

The real pysher.Pusher is not exercised — a fake factory replaces it so
tests run fast, deterministically, and without opening real WebSockets.
The HTTP auth call IS exercised against pytest-httpserver to keep the
broadcasting-auth contract honest.
"""
from __future__ import annotations

import json
import logging
from unittest.mock import MagicMock

import pytest

pytest.importorskip("httpx")
pytest.importorskip("pytest_httpserver")

from pytest_httpserver import HTTPServer  # noqa: E402

from harbormaster.fleetq.relay import BridgeRelay  # noqa: E402

# ----- helpers --------------------------------------------------------------


class _FakePusher:
    """Mimics pysher.Pusher's connection / subscribe / connect / disconnect."""

    def __init__(self, *, key, host, port, secure):
        self.init_args = {"key": key, "host": host, "port": port, "secure": secure}
        self.connection = MagicMock()
        self.subscriptions: dict[str, MagicMock] = {}
        self.connect_called = False
        self.disconnect_called = False
        # Capture handlers bound to connection events so the test can fire them.
        self._connection_handlers: dict[str, callable] = {}
        self.connection.bind.side_effect = self._capture_connection_bind

    def _capture_connection_bind(self, event, handler):
        self._connection_handlers[event] = handler

    def fire_connection_event(self, event, data):
        """Test helper: simulate Pusher firing a connection-level event."""
        if event in self._connection_handlers:
            self._connection_handlers[event](data)

    def subscribe(self, channel_name, auth=None):
        ch = MagicMock()
        ch.subscribe_args = {"channel_name": channel_name, "auth": auth}
        ch._handlers = {}

        def bind(event, handler):
            ch._handlers[event] = handler

        ch.bind.side_effect = bind
        ch.fire = lambda event, data=None: ch._handlers[event](data)
        self.subscriptions[channel_name] = ch
        return ch

    def connect(self):
        self.connect_called = True

    def disconnect(self):
        self.disconnect_called = True


@pytest.fixture
def fake_pusher_factory():
    """Returns (factory, captured_pushers) so tests can introspect what was built."""
    captured: list[_FakePusher] = []

    def factory(*, key, host, port, secure):
        p = _FakePusher(key=key, host=host, port=port, secure=secure)
        captured.append(p)
        return p

    factory.captured = captured  # type: ignore[attr-defined]
    return factory


@pytest.fixture
def relay(fake_pusher_factory, httpserver: HTTPServer):
    base_url = httpserver.url_for("").rstrip("/")
    r = BridgeRelay(
        base_url=base_url,
        api_token="test-token",
        team_id="team-uuid-9",
        app_key="reverb-app-key-xyz",
        relay_url="wss://app.fleetq.net:443",
        pusher_factory=fake_pusher_factory,
    )
    yield r
    r.stop()


# ----- constructor validation ----------------------------------------------


def test_constructor_requires_team_id(fake_pusher_factory):
    with pytest.raises(ValueError, match="team_id"):
        BridgeRelay(
            base_url="https://x", api_token="t", team_id="",
            app_key="a", relay_url="wss://x:443",
            pusher_factory=fake_pusher_factory,
        )


def test_constructor_requires_app_key(fake_pusher_factory):
    with pytest.raises(ValueError, match="app_key"):
        BridgeRelay(
            base_url="https://x", api_token="t", team_id="team",
            app_key="", relay_url="wss://x:443",
            pusher_factory=fake_pusher_factory,
        )


def test_constructor_requires_relay_url(fake_pusher_factory):
    with pytest.raises(ValueError, match="relay_url"):
        BridgeRelay(
            base_url="https://x", api_token="t", team_id="team",
            app_key="a", relay_url="",
            pusher_factory=fake_pusher_factory,
        )


def test_channel_name_is_private_daemon_team(relay):
    assert relay.channel_name == "private-daemon.team-uuid-9"


# ----- parse_relay_url ------------------------------------------------------


def test_parse_relay_url_wss_default_port(fake_pusher_factory):
    r = BridgeRelay(
        base_url="https://x", api_token="t", team_id="team",
        app_key="a", relay_url="wss://app.fleetq.net",
        pusher_factory=fake_pusher_factory,
    )
    host, port, secure = r.parse_relay_url()
    assert host == "app.fleetq.net"
    assert port == 443
    assert secure is True


def test_parse_relay_url_ws_default_port(fake_pusher_factory):
    r = BridgeRelay(
        base_url="https://x", api_token="t", team_id="team",
        app_key="a", relay_url="ws://localhost",
        pusher_factory=fake_pusher_factory,
    )
    host, port, secure = r.parse_relay_url()
    assert host == "localhost"
    assert port == 80
    assert secure is False


def test_parse_relay_url_explicit_port(fake_pusher_factory):
    r = BridgeRelay(
        base_url="https://x", api_token="t", team_id="team",
        app_key="a", relay_url="wss://app.fleetq.net:8443",
        pusher_factory=fake_pusher_factory,
    )
    _, port, _ = r.parse_relay_url()
    assert port == 8443


def test_parse_relay_url_rejects_no_host(fake_pusher_factory):
    r = BridgeRelay(
        base_url="https://x", api_token="t", team_id="team",
        app_key="a", relay_url="wss://:443",
        pusher_factory=fake_pusher_factory,
    )
    with pytest.raises(ValueError, match="missing hostname"):
        r.parse_relay_url()


# ----- fetch_channel_auth ---------------------------------------------------


def test_fetch_channel_auth_sends_documented_payload(httpserver: HTTPServer, relay):
    httpserver.expect_request(
        "/api/v1/bridge/broadcasting-auth",
        method="POST",
        headers={"Authorization": "Bearer test-token"},
    ).respond_with_json({"auth": "reverb-app-key-xyz:abc123hex"})

    auth = relay.fetch_channel_auth("socket-456")
    assert auth == "reverb-app-key-xyz:abc123hex"

    request = httpserver.log[-1][0]
    body = request.get_data().decode()
    assert "socket_id=socket-456" in body
    assert "channel_name=private-daemon.team-uuid-9" in body


def test_fetch_channel_auth_raises_on_403(httpserver: HTTPServer, relay):
    import httpx

    httpserver.expect_request(
        "/api/v1/bridge/broadcasting-auth", method="POST"
    ).respond_with_data("Forbidden", status=403)
    with pytest.raises(httpx.HTTPStatusError):
        relay.fetch_channel_auth("socket-456")


def test_fetch_channel_auth_rejects_missing_auth_field(httpserver: HTTPServer, relay):
    httpserver.expect_request(
        "/api/v1/bridge/broadcasting-auth", method="POST"
    ).respond_with_json({"unexpected": "shape"})
    with pytest.raises(RuntimeError, match="unexpected body"):
        relay.fetch_channel_auth("socket-456")


# ----- start / stop lifecycle ----------------------------------------------


def test_start_constructs_pusher_with_parsed_url_and_calls_connect(relay, fake_pusher_factory):
    relay.start()
    captured = fake_pusher_factory.captured
    assert len(captured) == 1
    p = captured[0]
    assert p.init_args == {
        "key": "reverb-app-key-xyz",
        "host": "app.fleetq.net",
        "port": 443,
        "secure": True,
    }
    assert p.connect_called is True


def test_start_binds_connection_established_handler(relay, fake_pusher_factory):
    relay.start()
    p = fake_pusher_factory.captured[0]
    assert "pusher:connection_established" in p._connection_handlers


def test_stop_calls_disconnect_and_resets_state(relay, fake_pusher_factory, httpserver):
    httpserver.expect_request("/api/v1/bridge/broadcasting-auth").respond_with_json(
        {"auth": "reverb-app-key-xyz:hex"}
    )
    relay.start()
    p = fake_pusher_factory.captured[0]

    # Simulate a successful connection so we have state to clear
    p.fire_connection_event(
        "pusher:connection_established", json.dumps({"socket_id": "s-1"})
    )
    assert relay.socket_id == "s-1"

    relay.stop()
    assert p.disconnect_called is True
    assert relay.socket_id is None
    assert relay.subscribed is False


def test_stop_is_idempotent_when_never_started(relay):
    relay.stop()  # no-op, must not raise


# ----- connection_established → auth → subscribe flow ---------------------


def test_connection_established_subscribes_with_fetched_auth(
    relay, fake_pusher_factory, httpserver
):
    httpserver.expect_request(
        "/api/v1/bridge/broadcasting-auth", method="POST"
    ).respond_with_json({"auth": "reverb-app-key-xyz:signed-hex"})

    relay.start()
    p = fake_pusher_factory.captured[0]

    p.fire_connection_event(
        "pusher:connection_established", json.dumps({"socket_id": "sock-77"})
    )

    assert relay.socket_id == "sock-77"
    assert "private-daemon.team-uuid-9" in p.subscriptions
    ch = p.subscriptions["private-daemon.team-uuid-9"]
    assert ch.subscribe_args["auth"] == "reverb-app-key-xyz:signed-hex"
    # Verify both event handlers were bound on the channel
    assert "agent.request" in ch._handlers
    assert "pusher_internal:subscription_succeeded" in ch._handlers


def test_connection_established_handles_dict_payload(
    relay, fake_pusher_factory, httpserver
):
    """pysher may pass either a JSON string or a pre-parsed dict — accept both."""
    httpserver.expect_request(
        "/api/v1/bridge/broadcasting-auth"
    ).respond_with_json({"auth": "k:hex"})

    relay.start()
    p = fake_pusher_factory.captured[0]
    p.fire_connection_event(
        "pusher:connection_established", {"socket_id": "sock-dict"}
    )
    assert relay.socket_id == "sock-dict"


def test_connection_established_without_socket_id_is_logged_and_swallowed(
    relay, fake_pusher_factory, caplog
):
    relay.start()
    p = fake_pusher_factory.captured[0]
    with caplog.at_level(logging.ERROR, logger="harbormaster.fleetq.relay"):
        p.fire_connection_event("pusher:connection_established", json.dumps({}))
    assert relay.socket_id is None
    assert any("without socket_id" in rec.message for rec in caplog.records)


def test_auth_failure_logged_and_subscription_skipped(
    relay, fake_pusher_factory, httpserver, caplog
):
    httpserver.expect_request(
        "/api/v1/bridge/broadcasting-auth"
    ).respond_with_data("Forbidden", status=403)

    relay.start()
    p = fake_pusher_factory.captured[0]
    with caplog.at_level(logging.ERROR, logger="harbormaster.fleetq.relay"):
        p.fire_connection_event(
            "pusher:connection_established", json.dumps({"socket_id": "s"})
        )
    # Auth failed — no subscription
    assert "private-daemon.team-uuid-9" not in p.subscriptions
    assert any("channel auth failed" in rec.message for rec in caplog.records)


# ----- subscribed flag ------------------------------------------------------


def test_subscription_succeeded_flips_subscribed_flag(
    relay, fake_pusher_factory, httpserver
):
    httpserver.expect_request(
        "/api/v1/bridge/broadcasting-auth"
    ).respond_with_json({"auth": "k:hex"})

    relay.start()
    p = fake_pusher_factory.captured[0]
    p.fire_connection_event(
        "pusher:connection_established", json.dumps({"socket_id": "s"})
    )
    ch = p.subscriptions["private-daemon.team-uuid-9"]
    assert relay.subscribed is False
    ch.fire("pusher_internal:subscription_succeeded", {})
    assert relay.subscribed is True


# ----- agent.request handler (logging only in v1.0.0a8) ---------------------


def test_agent_request_logs_received_event(
    relay, fake_pusher_factory, httpserver, caplog
):
    httpserver.expect_request(
        "/api/v1/bridge/broadcasting-auth"
    ).respond_with_json({"auth": "k:hex"})

    relay.start()
    p = fake_pusher_factory.captured[0]
    p.fire_connection_event(
        "pusher:connection_established", json.dumps({"socket_id": "s"})
    )
    ch = p.subscriptions["private-daemon.team-uuid-9"]

    with caplog.at_level(logging.INFO, logger="harbormaster.fleetq.relay"):
        ch.fire(
            "agent.request",
            json.dumps({
                "request_id": "req-123",
                "server": "harbormaster",
                "method": "tools/call",
                "params": {"name": "list_projects"},
            }),
        )
    msgs = [rec.message for rec in caplog.records]
    assert any("agent.request received" in m for m in msgs)
    assert any("req-123" in m for m in msgs)


def test_agent_request_handles_dict_payload(
    relay, fake_pusher_factory, httpserver, caplog
):
    """If pusher delivers a pre-parsed dict instead of a JSON string,
    the handler should still log without crashing."""
    httpserver.expect_request(
        "/api/v1/bridge/broadcasting-auth"
    ).respond_with_json({"auth": "k:hex"})

    relay.start()
    p = fake_pusher_factory.captured[0]
    p.fire_connection_event(
        "pusher:connection_established", json.dumps({"socket_id": "s"})
    )
    ch = p.subscriptions["private-daemon.team-uuid-9"]

    with caplog.at_level(logging.INFO, logger="harbormaster.fleetq.relay"):
        ch.fire("agent.request", {"request_id": "abc"})
    assert any("abc" in rec.message for rec in caplog.records)


def test_agent_request_handles_garbage_payload(
    relay, fake_pusher_factory, httpserver, caplog
):
    """Hostile / malformed payload must not crash the listener thread."""
    httpserver.expect_request(
        "/api/v1/bridge/broadcasting-auth"
    ).respond_with_json({"auth": "k:hex"})

    relay.start()
    p = fake_pusher_factory.captured[0]
    p.fire_connection_event(
        "pusher:connection_established", json.dumps({"socket_id": "s"})
    )
    ch = p.subscriptions["private-daemon.team-uuid-9"]

    with caplog.at_level(logging.INFO, logger="harbormaster.fleetq.relay"):
        ch.fire("agent.request", "this isn't json")
    # No exception, log line still emitted
    assert any("agent.request received" in rec.message for rec in caplog.records)

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


def test_default_pusher_factory_uses_custom_host_kwarg(monkeypatch):
    """Regression for v2.0.1: pysher.Pusher's signature exposes the
    WebSocket host as `custom_host=`, NOT `host=`. Passing `host=`
    falls into pysher's `**thread_kwargs`, eventually reaching
    `Thread.__init__()` which raises TypeError. The default factory
    must therefore translate harbormaster's internal `host` parameter
    to pysher's `custom_host`."""
    from harbormaster.fleetq.relay import _default_pusher_factory

    captured: list[dict[str, object]] = []

    class FakePusher:
        def __init__(self, **kwargs):
            captured.append(kwargs)

    fake_pysher = type("M", (), {"Pusher": FakePusher})
    monkeypatch.setitem(__import__("sys").modules, "pysher", fake_pysher)

    _default_pusher_factory(
        key="k", host="app.fleetq.net", port=443, secure=True
    )

    assert captured == [
        {"key": "k", "custom_host": "app.fleetq.net", "port": 443, "secure": True}
    ]
    # And critically — no bare 'host' key (would crash pysher).
    assert "host" not in captured[0]


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


# ----- v2.0.0a7 publish surface (chunk_handler + client-relay events) ----


def test_publish_chunk_raises_before_subscribe(fake_pusher_factory):
    r = BridgeRelay(
        base_url="https://x",
        api_token="t",
        team_id="team",
        app_key="a",
        relay_url="wss://x:443",
        pusher_factory=fake_pusher_factory,
    )
    with pytest.raises(RuntimeError, match="cannot publish_chunk"):
        r.publish_chunk(request_id="abc", chunk="hi", done=False)


def test_publish_error_raises_before_subscribe(fake_pusher_factory):
    r = BridgeRelay(
        base_url="https://x",
        api_token="t",
        team_id="team",
        app_key="a",
        relay_url="wss://x:443",
        pusher_factory=fake_pusher_factory,
    )
    with pytest.raises(RuntimeError, match="cannot publish_error"):
        r.publish_error(request_id="abc", error="boom")


def _subscribed_relay(relay, fake_pusher_factory, httpserver):
    """Drive the relay through connect → auth → subscribe so the channel
    object is captured and `publish_*` becomes available."""
    httpserver.expect_request(
        "/api/v1/bridge/broadcasting-auth"
    ).respond_with_json({"auth": "k:hex"})
    relay.start()
    p = fake_pusher_factory.captured[0]
    p.fire_connection_event(
        "pusher:connection_established", json.dumps({"socket_id": "s"})
    )
    return p.subscriptions["private-daemon.team-uuid-9"]


def test_publish_chunk_triggers_client_relay_event(
    relay, fake_pusher_factory, httpserver
):
    ch = _subscribed_relay(relay, fake_pusher_factory, httpserver)
    relay.publish_chunk(request_id="r1", chunk="hello", done=False)
    ch.trigger.assert_called_once()
    event, data = ch.trigger.call_args.args
    assert event == "client-relay.chunk"
    assert data == {
        "request_id": "r1",
        "chunk": "hello",
        "done": False,
        "usage": None,
    }


def test_publish_chunk_passes_done_and_usage(
    relay, fake_pusher_factory, httpserver
):
    ch = _subscribed_relay(relay, fake_pusher_factory, httpserver)
    relay.publish_chunk(
        request_id="r1",
        chunk="",
        done=True,
        usage={"prompt_tokens": 10, "completion_tokens": 20},
    )
    _, data = ch.trigger.call_args.args
    assert data["done"] is True
    assert data["usage"] == {"prompt_tokens": 10, "completion_tokens": 20}


def test_publish_error_triggers_client_relay_error(
    relay, fake_pusher_factory, httpserver
):
    ch = _subscribed_relay(relay, fake_pusher_factory, httpserver)
    relay.publish_error(request_id="r1", error="exec failed")
    ch.trigger.assert_called_once()
    event, data = ch.trigger.call_args.args
    assert event == "client-relay.error"
    assert data == {"request_id": "r1", "error": "exec failed"}


def test_chunk_handler_streams_yielded_chunks_with_final_sentinel(
    fake_pusher_factory, httpserver
):
    """When chunk_handler is wired, agent.request payloads are dispatched
    to the handler and each yielded text chunk is published as a
    client-relay.chunk event. The final empty-chunk done=true sentinel
    closes the FleetQ-side popChunk loop."""

    def handler(payload):
        assert payload["request_id"] == "r-1"
        yield "Hel"
        yield "lo "
        yield "world"

    httpserver.expect_request(
        "/api/v1/bridge/broadcasting-auth"
    ).respond_with_json({"auth": "k:hex"})

    r = BridgeRelay(
        base_url=httpserver.url_for("").rstrip("/"),
        api_token="t",
        team_id="team-uuid-9",
        app_key="a",
        relay_url="wss://x:443",
        pusher_factory=fake_pusher_factory,
        chunk_handler=handler,
    )
    try:
        r.start()
        p = fake_pusher_factory.captured[0]
        p.fire_connection_event(
            "pusher:connection_established", json.dumps({"socket_id": "s"})
        )
        ch = p.subscriptions["private-daemon.team-uuid-9"]
        ch.fire(
            "agent.request",
            json.dumps({"request_id": "r-1", "method": "ask", "server": "harbormaster"}),
        )
    finally:
        r.stop()

    triggered = [(call.args[0], call.args[1]) for call in ch.trigger.call_args_list]
    # 3 chunks (text deltas) + 1 final sentinel (done=true)
    assert len(triggered) == 4
    for event, _ in triggered:
        assert event == "client-relay.chunk"
    assert [d["chunk"] for _, d in triggered] == ["Hel", "lo ", "world", ""]
    assert [d["done"] for _, d in triggered] == [False, False, False, True]
    assert all(d["request_id"] == "r-1" for _, d in triggered)


def test_chunk_handler_exception_publishes_client_relay_error(
    fake_pusher_factory, httpserver, caplog
):
    def boom(payload):
        yield "Partial"
        raise RuntimeError("handler failed mid-stream")

    httpserver.expect_request(
        "/api/v1/bridge/broadcasting-auth"
    ).respond_with_json({"auth": "k:hex"})

    r = BridgeRelay(
        base_url=httpserver.url_for("").rstrip("/"),
        api_token="t",
        team_id="team-uuid-9",
        app_key="a",
        relay_url="wss://x:443",
        pusher_factory=fake_pusher_factory,
        chunk_handler=boom,
    )
    try:
        r.start()
        p = fake_pusher_factory.captured[0]
        p.fire_connection_event(
            "pusher:connection_established", json.dumps({"socket_id": "s"})
        )
        ch = p.subscriptions["private-daemon.team-uuid-9"]
        with caplog.at_level(logging.ERROR, logger="harbormaster.fleetq.relay"):
            ch.fire(
                "agent.request",
                json.dumps({"request_id": "r-1", "method": "x"}),
            )
    finally:
        r.stop()

    events = [(c.args[0], c.args[1]) for c in ch.trigger.call_args_list]
    # First a chunk (text delta), then a client-relay.error
    assert events[0][0] == "client-relay.chunk"
    assert events[0][1]["chunk"] == "Partial"
    error_events = [e for e in events if e[0] == "client-relay.error"]
    assert len(error_events) == 1
    assert error_events[0][1] == {
        "request_id": "r-1",
        "error": "handler failed mid-stream",
    }


def test_chunk_handler_skipped_when_no_request_id(
    fake_pusher_factory, httpserver, caplog
):
    """A payload without request_id can't be routed back — must skip
    dispatch + log a warning, never call the handler."""
    handler_called: list[bool] = []

    def handler(_payload):
        handler_called.append(True)
        yield "noop"

    httpserver.expect_request(
        "/api/v1/bridge/broadcasting-auth"
    ).respond_with_json({"auth": "k:hex"})

    r = BridgeRelay(
        base_url=httpserver.url_for("").rstrip("/"),
        api_token="t",
        team_id="team-uuid-9",
        app_key="a",
        relay_url="wss://x:443",
        pusher_factory=fake_pusher_factory,
        chunk_handler=handler,
    )
    try:
        r.start()
        p = fake_pusher_factory.captured[0]
        p.fire_connection_event(
            "pusher:connection_established", json.dumps({"socket_id": "s"})
        )
        ch = p.subscriptions["private-daemon.team-uuid-9"]
        with caplog.at_level(logging.WARNING, logger="harbormaster.fleetq.relay"):
            ch.fire("agent.request", json.dumps({"method": "x"}))
    finally:
        r.stop()

    assert handler_called == []
    ch.trigger.assert_not_called()


def test_chunk_handler_default_none_keeps_v1_log_only_behaviour(
    relay, fake_pusher_factory, httpserver, caplog
):
    """Without chunk_handler set, agent.request logs as v1 — no triggers."""
    ch = _subscribed_relay(relay, fake_pusher_factory, httpserver)
    with caplog.at_level(logging.INFO, logger="harbormaster.fleetq.relay"):
        ch.fire(
            "agent.request",
            json.dumps({"request_id": "r-1", "method": "x"}),
        )
    ch.trigger.assert_not_called()
    assert any("agent.request received" in r.message for r in caplog.records)


# --- v3.0.0a5: worker thread ---------------------------------------------


class _StubChannel:
    def __init__(self):
        self.events = []

    def trigger(self, event, data):
        self.events.append((event, data))


def test_relay_worker_thread_dispatches_off_pysher_thread(fake_pusher_factory):
    """When worker_thread=True, the chunk_handler must run on a dedicated
    thread — verified by capturing thread.ident from inside the handler."""
    import threading
    import time

    handler_thread_ids = []

    def slow_handler(payload):
        handler_thread_ids.append(threading.get_ident())
        time.sleep(0.05)
        yield "result"

    relay = BridgeRelay(
        base_url="http://example",
        api_token="t",
        team_id="team-1",
        app_key="key",
        relay_url="wss://example:443",
        pusher_factory=fake_pusher_factory,
        chunk_handler=slow_handler,
        worker_thread=True,
    )
    relay.start()
    # Mock-out subscribe completion so trigger() works.
    relay._channel = _StubChannel()

    main_tid = threading.get_ident()
    # Push two requests through the pysher-side entry point.
    relay._on_agent_request({"request_id": "req-1", "method": "tools/list"})
    relay._on_agent_request({"request_id": "req-2", "method": "tools/list"})

    # Give the worker time to drain.
    deadline = time.time() + 2.0
    while len(handler_thread_ids) < 2 and time.time() < deadline:
        time.sleep(0.01)

    relay.stop()

    assert len(handler_thread_ids) == 2
    # Handler ran on a non-main, non-test thread.
    assert all(tid != main_tid for tid in handler_thread_ids)
    # Both handler invocations ran on the SAME worker thread (single-worker).
    assert handler_thread_ids[0] == handler_thread_ids[1]


def test_relay_worker_thread_disabled_falls_back_to_inline(fake_pusher_factory):
    """worker_thread=False keeps v2.0.0a7 inline-dispatch behaviour —
    handler runs synchronously on the pysher (test) thread."""
    import threading

    handler_thread_ids = []

    def handler(payload):
        handler_thread_ids.append(threading.get_ident())
        yield "ok"

    relay = BridgeRelay(
        base_url="http://example",
        api_token="t",
        team_id="team-1",
        app_key="key",
        relay_url="wss://example:443",
        pusher_factory=fake_pusher_factory,
        chunk_handler=handler,
        worker_thread=False,
    )
    relay._channel = _StubChannel()

    main_tid = threading.get_ident()
    relay._on_agent_request({"request_id": "req-1", "method": "tools/list"})

    # Inline dispatch ran on this test's thread.
    assert handler_thread_ids == [main_tid]


def test_relay_worker_queue_full_publishes_error(fake_pusher_factory):
    """A full inbound queue must NOT block the pysher thread; the
    overflow path publishes a client-relay.error and drops the request."""
    import threading
    import time

    handler_started = threading.Event()
    handler_release = threading.Event()

    def slow_handler(payload):
        handler_started.set()
        # Block until the test releases — keeps the worker busy so
        # subsequent puts saturate the queue.
        handler_release.wait(timeout=2.0)
        yield "done"

    relay = BridgeRelay(
        base_url="http://example",
        api_token="t",
        team_id="team-1",
        app_key="key",
        relay_url="wss://example:443",
        pusher_factory=fake_pusher_factory,
        chunk_handler=slow_handler,
        worker_thread=True,
        worker_queue_max=1,
    )
    relay.start()
    stub = _StubChannel()
    relay._channel = stub

    # First request: starts the slow handler.
    relay._on_agent_request({"request_id": "req-1", "method": "tools/list"})
    assert handler_started.wait(timeout=1.0)

    # Second request: still fits in the queue (queue_max=1).
    relay._on_agent_request({"request_id": "req-2", "method": "tools/list"})
    # Third request: queue full → must publish error, NOT block.
    relay._on_agent_request({"request_id": "req-3", "method": "tools/list"})

    # Verify error event for req-3 (or req-2 — whichever overflowed).
    error_events = [e for e in stub.events if e[0] == "client-relay.error"]
    assert any("queue full" in ev[1]["error"] for ev in error_events)

    # Release the slow handler so stop() can join cleanly.
    handler_release.set()
    # Give worker a moment to drain remaining queued items.
    time.sleep(0.2)
    relay.stop()


def test_relay_worker_thread_clean_shutdown(fake_pusher_factory):
    """stop() must terminate the worker thread within the join timeout."""
    relay = BridgeRelay(
        base_url="http://example",
        api_token="t",
        team_id="team-1",
        app_key="key",
        relay_url="wss://example:443",
        pusher_factory=fake_pusher_factory,
        chunk_handler=lambda payload: iter([]),
        worker_thread=True,
    )
    relay.start()
    worker = relay._worker_thread_handle
    assert worker is not None and worker.is_alive()

    relay.stop()

    assert relay._worker_thread_handle is None
    assert relay._worker_queue is None
    assert not worker.is_alive()


# --- v4.0.0a6: multi-worker dispatcher pool -----------------------------


def test_relay_single_worker_default_no_pool(fake_pusher_factory):
    """Default dispatcher_max_workers=1 → no ThreadPoolExecutor created."""
    relay = BridgeRelay(
        base_url="http://example",
        api_token="t",
        team_id="team-1",
        app_key="key",
        relay_url="wss://example:443",
        pusher_factory=fake_pusher_factory,
        chunk_handler=lambda payload: iter([]),
        worker_thread=True,
    )
    relay.start()
    assert relay._dispatcher_pool is None
    relay.stop()


def test_relay_multi_worker_creates_pool(fake_pusher_factory):
    """dispatcher_max_workers=4 → ThreadPoolExecutor instantiated."""
    relay = BridgeRelay(
        base_url="http://example",
        api_token="t",
        team_id="team-1",
        app_key="key",
        relay_url="wss://example:443",
        pusher_factory=fake_pusher_factory,
        chunk_handler=lambda payload: iter([]),
        worker_thread=True,
        dispatcher_max_workers=4,
    )
    relay.start()
    assert relay._dispatcher_pool is not None
    relay.stop()
    # After stop the pool reference is cleared.
    assert relay._dispatcher_pool is None


def test_relay_multi_worker_dispatches_concurrently(fake_pusher_factory):
    """With dispatcher_max_workers > 1, two requests should run in
    overlapping windows (unlike single-worker which serializes)."""
    import threading
    import time

    in_flight = []
    in_flight_lock = threading.Lock()
    max_concurrent = [0]

    def slow_handler(payload):
        with in_flight_lock:
            in_flight.append(threading.get_ident())
            max_concurrent[0] = max(max_concurrent[0], len(in_flight))
        time.sleep(0.05)
        with in_flight_lock:
            in_flight.remove(threading.get_ident())
        yield "ok"

    relay = BridgeRelay(
        base_url="http://example",
        api_token="t",
        team_id="team-1",
        app_key="key",
        relay_url="wss://example:443",
        pusher_factory=fake_pusher_factory,
        chunk_handler=slow_handler,
        worker_thread=True,
        dispatcher_max_workers=4,
    )
    relay.start()

    class _StubChannel2:
        def __init__(self):
            self.events = []
        def trigger(self, event, data):
            self.events.append((event, data))
    relay._channel = _StubChannel2()

    # Submit 4 requests in rapid succession.
    for i in range(4):
        relay._on_agent_request({"request_id": f"req-{i}", "method": "tools/list"})

    # Give the pool time to drain.
    deadline = time.time() + 2.0
    while len(relay._channel.events) < 8 and time.time() < deadline:
        time.sleep(0.01)

    relay.stop()

    # With max_workers=4 and slow_handler holding for 50ms, multiple
    # dispatches should have overlapped — max_concurrent must be > 1.
    assert max_concurrent[0] > 1, (
        f"expected overlapping dispatches, got max_concurrent={max_concurrent[0]}"
    )


def test_relay_dispatcher_max_workers_clamped_to_min_1(fake_pusher_factory):
    """dispatcher_max_workers=0 must clamp to 1 (single-worker fallback)."""
    relay = BridgeRelay(
        base_url="http://example",
        api_token="t",
        team_id="team-1",
        app_key="key",
        relay_url="wss://example:443",
        pusher_factory=fake_pusher_factory,
        chunk_handler=lambda payload: iter([]),
        worker_thread=True,
        dispatcher_max_workers=0,
    )
    assert relay._dispatcher_max_workers == 1


# --- v5.0.0a3: per-tool safety gate in worker loop ----------------------


def test_relay_unsafe_tool_routes_to_inline_dispatch_under_pool(fake_pusher_factory):
    """When the pool is enabled but the tool is unsafe, dispatch must
    run inline (on the worker thread, not the pool)."""
    import threading
    import time

    handler_threads = []

    def handler(payload):
        handler_threads.append(threading.get_ident())
        time.sleep(0.02)
        yield "ok"

    relay = BridgeRelay(
        base_url="http://example",
        api_token="t",
        team_id="team-1",
        app_key="key",
        relay_url="wss://example:443",
        pusher_factory=fake_pusher_factory,
        chunk_handler=handler,
        worker_thread=True,
        dispatcher_max_workers=4,
        # third_party_plugin is NOT in SAFE_FOR_PARALLEL.
    )
    relay.start()

    class _StubChannel3:
        def __init__(self): self.events = []
        def trigger(self, event, data): self.events.append((event, data))
    relay._channel = _StubChannel3()

    # Send 3 requests for an unknown tool — must serialize on worker thread.
    for i in range(3):
        relay._on_agent_request({
            "request_id": f"req-{i}",
            "method": "tools/call",
            "params": {"name": "third_party_plugin", "arguments": {}},
        })

    deadline = time.time() + 2.0
    while len(handler_threads) < 3 and time.time() < deadline:
        time.sleep(0.01)

    relay.stop()

    assert len(handler_threads) == 3
    # All three dispatched on the SAME thread (the worker), not the pool.
    assert len(set(handler_threads)) == 1


def test_relay_explicit_unsafe_tools_override_routes_to_inline(fake_pusher_factory):
    """Operator deny list: even ask_project (default-safe) routes to
    single-worker when listed in dispatcher_unsafe_tools."""
    import threading
    import time

    handler_threads = []

    def handler(payload):
        handler_threads.append(threading.get_ident())
        time.sleep(0.02)
        yield "ok"

    relay = BridgeRelay(
        base_url="http://example",
        api_token="t",
        team_id="team-1",
        app_key="key",
        relay_url="wss://example:443",
        pusher_factory=fake_pusher_factory,
        chunk_handler=handler,
        worker_thread=True,
        dispatcher_max_workers=4,
        dispatcher_unsafe_tools=["ask_project"],
    )
    relay.start()

    class _StubChannel4:
        def __init__(self): self.events = []
        def trigger(self, event, data): self.events.append((event, data))
    relay._channel = _StubChannel4()

    for i in range(3):
        relay._on_agent_request({
            "request_id": f"req-{i}",
            "method": "tools/call",
            "params": {"name": "ask_project", "arguments": {"name": "x", "question": "y"}},
        })

    deadline = time.time() + 2.0
    while len(handler_threads) < 3 and time.time() < deadline:
        time.sleep(0.01)

    relay.stop()

    # All three serialised on the worker (deny-listed tool).
    assert len(set(handler_threads)) == 1


def test_relay_safe_tool_still_uses_pool_under_mixed_workload(fake_pusher_factory):
    """When safe + unsafe tools both arrive, safe ones use the pool and
    unsafe ones use the worker — verified by counting distinct threads."""
    import threading
    import time

    threads_per_tool: dict[str, set[int]] = {"safe": set(), "unsafe": set()}
    lock = threading.Lock()

    def handler(payload):
        name = (payload.get("params") or {}).get("name", "?")
        kind = "safe" if name == "list_projects" else "unsafe"
        with lock:
            threads_per_tool[kind].add(threading.get_ident())
        time.sleep(0.05)
        yield "ok"

    relay = BridgeRelay(
        base_url="http://example",
        api_token="t",
        team_id="team-1",
        app_key="key",
        relay_url="wss://example:443",
        pusher_factory=fake_pusher_factory,
        chunk_handler=handler,
        worker_thread=True,
        dispatcher_max_workers=4,
    )
    relay.start()

    class _StubChannel5:
        def __init__(self): self.events = []
        def trigger(self, event, data): self.events.append((event, data))
    relay._channel = _StubChannel5()

    # 4 safe (list_projects) → should fan out across pool.
    for i in range(4):
        relay._on_agent_request({
            "request_id": f"safe-{i}",
            "method": "tools/call",
            "params": {"name": "list_projects", "arguments": {}},
        })
    # 4 unsafe (third_party) → all serialised on worker.
    for i in range(4):
        relay._on_agent_request({
            "request_id": f"unsafe-{i}",
            "method": "tools/call",
            "params": {"name": "third_party_unknown", "arguments": {}},
        })

    deadline = time.time() + 5.0
    while (
        len(threads_per_tool["safe"]) + len(threads_per_tool["unsafe"]) < 2
        and time.time() < deadline
    ):
        time.sleep(0.01)

    # Wait for everything to drain so we don't race the assertions.
    time.sleep(0.5)
    relay.stop()

    # Safe tools used the pool — multiple worker IDs likely.
    # Unsafe tools all on one thread (the worker).
    assert len(threads_per_tool["unsafe"]) == 1
    # Pool path saw at least one thread (could be 1..4 depending on
    # scheduler); the key invariant is "different from the worker".
    assert threads_per_tool["safe"]
    assert threads_per_tool["safe"] != threads_per_tool["unsafe"]

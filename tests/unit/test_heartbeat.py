"""Tests for the heartbeat-loop daemon thread."""
from __future__ import annotations

import time
from unittest.mock import MagicMock

from harbormaster.fleetq.bridge import BridgeError, RegisterResponse
from harbormaster.fleetq.heartbeat import HeartbeatLoop


def _make_client(*, register_ok: bool = True, heartbeat_alive: bool = True) -> MagicMock:
    """Build a mock BridgeClient with the methods HeartbeatLoop calls."""
    client = MagicMock()
    if register_ok:
        client.register.return_value = RegisterResponse(
            session_id="s-1",
            team_id="t-1",
            connected_at="2026-05-08T12:00:00Z",
            reverb_app_key=None,
            reverb_relay_url=None,
        )
    else:
        client.register.side_effect = BridgeError("auth failed")

    client.heartbeat.return_value = heartbeat_alive
    client.disconnect.return_value = 1
    return client


# ----- start / stop lifecycle ----------------------------------------------


def test_start_calls_register_synchronously():
    client = _make_client()
    hb = HeartbeatLoop(client, endpoints={"mcp_servers": []}, interval=10)
    hb.start()
    try:
        assert client.register.call_count == 1
        assert hb.registered is True
    finally:
        hb.stop()


def test_start_is_idempotent():
    client = _make_client()
    hb = HeartbeatLoop(client, endpoints={}, interval=10)
    hb.start()
    hb.start()  # should not spawn a second thread
    try:
        assert client.register.call_count == 1
    finally:
        hb.stop()


def test_stop_calls_disconnect():
    client = _make_client()
    hb = HeartbeatLoop(client, endpoints={}, interval=10)
    hb.start()
    hb.stop()
    assert client.disconnect.call_count == 1
    assert client.close.call_count == 1


def test_stop_skips_disconnect_when_register_failed():
    """If initial register failed, we never bound a session — don't try to
    disconnect a session that doesn't exist on FleetQ."""
    client = _make_client(register_ok=False)
    hb = HeartbeatLoop(client, endpoints={}, interval=10)
    hb.start()
    hb.stop()
    assert client.disconnect.call_count == 0
    assert client.close.call_count == 1
    assert hb.registered is False


def test_stop_is_idempotent():
    client = _make_client()
    hb = HeartbeatLoop(client, endpoints={}, interval=10)
    hb.start()
    hb.stop()
    hb.stop()  # second stop is a no-op for disconnect
    assert client.disconnect.call_count == 1


# ----- loop behavior --------------------------------------------------------


def test_loop_heartbeats_periodically():
    client = _make_client()
    # tiny interval so the loop fires within the test's timeout
    hb = HeartbeatLoop(client, endpoints={}, interval=1)
    hb.start()
    # Wait for at least 2 heartbeat ticks
    deadline = time.monotonic() + 5.0
    while client.heartbeat.call_count < 2 and time.monotonic() < deadline:
        time.sleep(0.1)
    hb.stop()
    assert client.heartbeat.call_count >= 2


def test_loop_re_registers_on_session_lost():
    """heartbeat() returning False signals session lost — loop must call
    register() again with the same session_id."""
    client = _make_client()
    # First two heartbeats: alive. Then session-lost. Then alive again.
    client.heartbeat.side_effect = [True, False, True, True, True, True]
    hb = HeartbeatLoop(client, endpoints={}, interval=1)
    hb.start()
    # Wait for the re-register to happen
    deadline = time.monotonic() + 5.0
    while client.register.call_count < 2 and time.monotonic() < deadline:
        time.sleep(0.1)
    hb.stop()
    assert client.register.call_count >= 2  # initial + re-register


def test_loop_swallows_heartbeat_errors_and_continues():
    """A transient BridgeError during heartbeat must not kill the thread —
    next interval tick should retry."""
    client = _make_client()
    client.heartbeat.side_effect = [
        BridgeError("network wobble"),
        True,
        True,
        True,
    ]
    hb = HeartbeatLoop(client, endpoints={}, interval=1)
    hb.start()
    deadline = time.monotonic() + 5.0
    while client.heartbeat.call_count < 3 and time.monotonic() < deadline:
        time.sleep(0.1)
    hb.stop()
    # Despite the first heartbeat raising, subsequent ones still fired.
    assert client.heartbeat.call_count >= 3


def test_loop_retries_register_when_initial_failed():
    """If register() failed on start, the loop should keep trying every
    interval (e.g. FleetQ was briefly unreachable, comes back later)."""
    client = MagicMock()
    register_response = RegisterResponse(
        session_id="s-1",
        team_id="t-1",
        connected_at="2026-05-08T12:00:00Z",
        reverb_app_key=None,
        reverb_relay_url=None,
    )

    # Fail the first two attempts, succeed on the third. Use a callable so
    # we don't depend on side_effect-list iteration semantics.
    call_count = {"n": 0}

    def fake_register(endpoints):
        call_count["n"] += 1
        if call_count["n"] < 3:
            raise BridgeError("connect refused")
        return register_response

    client.register.side_effect = fake_register
    client.heartbeat.return_value = True
    client.disconnect.return_value = 1

    hb = HeartbeatLoop(client, endpoints={}, interval=1)
    hb.start()
    assert hb.registered is False  # initial register failed

    deadline = time.monotonic() + 8.0
    while not hb.registered and time.monotonic() < deadline:
        time.sleep(0.1)

    # Capture registered state BEFORE stop() — stop() clears the flag after
    # a successful disconnect, so checking after stop() would always be False.
    became_registered = hb.registered
    register_calls_before_stop = client.register.call_count
    hb.stop()

    assert became_registered is True, (
        f"loop did not recover from initial register failure within 8s "
        f"(register call_count={register_calls_before_stop})"
    )
    assert register_calls_before_stop >= 3


# ----- thread safety --------------------------------------------------------


def test_thread_is_daemon():
    """Daemon flag means the heartbeat thread won't keep the process alive
    after main exits, even if stop() isn't called."""
    client = _make_client()
    hb = HeartbeatLoop(client, endpoints={}, interval=10)
    hb.start()
    try:
        assert hb._thread is not None
        assert hb._thread.daemon is True
    finally:
        hb.stop()


def test_thread_named_for_diagnosability():
    client = _make_client()
    hb = HeartbeatLoop(client, endpoints={}, interval=10)
    hb.start()
    try:
        assert hb._thread is not None
        assert hb._thread.name == "fleetq-heartbeat"
    finally:
        hb.stop()


# ----- endpoints_factory drift detection -----------------------------------


def test_endpoints_factory_pushes_update_when_manifest_changes():
    """If the factory returns a manifest different from what was registered,
    the loop must call client.update_endpoints with the new value."""
    client = _make_client()

    initial = {"mcp_servers": [{"name": "harbormaster"}]}
    drifted = {"mcp_servers": [{"name": "harbormaster"}, {"name": "extra"}]}
    factory_state = {"current": initial}

    def factory() -> dict:
        return factory_state["current"]

    hb = HeartbeatLoop(
        client,
        endpoints=initial,
        interval=1,
        endpoints_factory=factory,
    )
    hb.start()
    try:
        # Wait for at least one heartbeat tick so the factory's identity
        # output is observed (and ignored — no drift yet).
        deadline = time.monotonic() + 5.0
        while client.heartbeat.call_count < 1 and time.monotonic() < deadline:
            time.sleep(0.1)

        # Identity output should NOT have triggered an update.
        assert client.update_endpoints.call_count == 0

        # Now drift the factory output.
        factory_state["current"] = drifted

        # Wait for the next tick to detect the drift and push it.
        deadline = time.monotonic() + 5.0
        while client.update_endpoints.call_count < 1 and time.monotonic() < deadline:
            time.sleep(0.1)

        assert client.update_endpoints.call_count >= 1
        client.update_endpoints.assert_called_with(drifted)
    finally:
        hb.stop()


def test_endpoints_factory_does_not_push_when_unchanged():
    """When the factory consistently returns the same manifest as the last
    push, no update_endpoints calls should ever be issued."""
    client = _make_client()
    initial = {"mcp_servers": [{"name": "harbormaster"}]}

    hb = HeartbeatLoop(
        client,
        endpoints=initial,
        interval=1,
        endpoints_factory=lambda: dict(initial),
    )
    hb.start()
    try:
        # Wait for at least three heartbeat ticks so the factory has had
        # multiple opportunities to misbehave.
        deadline = time.monotonic() + 5.0
        while client.heartbeat.call_count < 3 and time.monotonic() < deadline:
            time.sleep(0.1)
    finally:
        hb.stop()
    assert client.update_endpoints.call_count == 0


def test_endpoints_factory_swallows_factory_exceptions():
    """A raising factory must not kill the heartbeat thread — the loop
    should keep heartbeating and try the factory again next tick."""
    client = _make_client()

    call_count = {"n": 0}

    def factory() -> dict:
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise RuntimeError("config file vanished")
        return {"mcp_servers": [{"name": "harbormaster"}, {"name": "recovered"}]}

    hb = HeartbeatLoop(
        client,
        endpoints={"mcp_servers": [{"name": "harbormaster"}]},
        interval=1,
        endpoints_factory=factory,
    )
    hb.start()
    try:
        # Wait for the second factory call (after the first raised) to
        # produce drift and push.
        deadline = time.monotonic() + 5.0
        while client.update_endpoints.call_count < 1 and time.monotonic() < deadline:
            time.sleep(0.1)
    finally:
        hb.stop()
    assert client.update_endpoints.call_count >= 1


def test_endpoints_factory_swallows_update_endpoints_failures():
    """A failing update_endpoints must not advance the drift baseline,
    so the next tick retries the same diff."""
    client = _make_client()
    client.update_endpoints.side_effect = [
        BridgeError("temporary 500"),
        None,  # second attempt succeeds
    ]

    drifted = {"mcp_servers": [{"name": "harbormaster"}, {"name": "extra"}]}

    hb = HeartbeatLoop(
        client,
        endpoints={"mcp_servers": [{"name": "harbormaster"}]},
        interval=1,
        endpoints_factory=lambda: drifted,
    )
    hb.start()
    try:
        # Wait for two update_endpoints attempts (first raises, second wins).
        deadline = time.monotonic() + 6.0
        while client.update_endpoints.call_count < 2 and time.monotonic() < deadline:
            time.sleep(0.1)
    finally:
        hb.stop()
    assert client.update_endpoints.call_count >= 2
    # Both attempts pushed the same diff (baseline didn't advance after the
    # first raise).
    assert client.update_endpoints.call_args_list[0].args[0] == drifted
    assert client.update_endpoints.call_args_list[1].args[0] == drifted


def test_no_endpoints_factory_means_static_manifest():
    """Backwards-compatible default: without a factory, no update_endpoints
    calls are ever issued, even after many heartbeats."""
    client = _make_client()
    hb = HeartbeatLoop(client, endpoints={"mcp_servers": []}, interval=1)
    hb.start()
    try:
        deadline = time.monotonic() + 4.0
        while client.heartbeat.call_count < 3 and time.monotonic() < deadline:
            time.sleep(0.1)
    finally:
        hb.stop()
    assert client.update_endpoints.call_count == 0

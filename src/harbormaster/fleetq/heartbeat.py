"""Background heartbeat thread for the FleetQ Bridge integration.

Owns the lifecycle: register on start, heartbeat at interval, re-register
on session loss (404 from heartbeat), optionally re-publish the endpoints
manifest when an `endpoints_factory` reports drift, disconnect + close on
stop.

Threading instead of asyncio because FastMCP's stdio transport runs as a
blocking sync mcp.run() call. The HTTP-transport path is async, but for
v1.0.0a6 we want a single mechanism that works for both transports.
"""
from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from typing import Any

from harbormaster.fleetq.bridge import BridgeClient, BridgeError, RegisterResponse
from harbormaster.fleetq.state import BridgeStateWriter

logger = logging.getLogger(__name__)

# Cap for the register-retry backoff. A persistent auth failure (an expired
# or revoked token → HTTP 401) is not transient: retrying every `interval`
# seconds forever just hammers FleetQ and floods the client's stderr (a real
# incident produced 14k+ 401 lines / 5.5MB in a single Claude Desktop log).
# Back off exponentially from `interval` up to this ceiling instead.
_MAX_REGISTER_BACKOFF_SECONDS = 900  # 15 minutes


class HeartbeatLoop:
    """Daemon thread wrapping a BridgeClient.

    Usage:
        hb = HeartbeatLoop(client, endpoints, interval=30)
        hb.start()
        ...
        hb.stop()

    Optional config-watch behaviour: pass an `endpoints_factory` callable.
    On every heartbeat tick the factory is invoked; if its output differs
    from what FleetQ was last told, `update_endpoints` is issued so the
    Bridge manifest stays in sync with the running process. The factory
    should be cheap and side-effect-free — it is called every `interval`
    seconds.

    Optional cross-process state surfacing: pass a `state_writer`
    (BridgeStateWriter). Each lifecycle event (register, heartbeat,
    session loss, stop) writes a snapshot to disk so the harbormaster-ui
    process can render live status (v3.0.0a2).
    """

    def __init__(
        self,
        client: BridgeClient,
        endpoints: dict[str, Any],
        *,
        interval: int = 30,
        endpoints_factory: Callable[[], dict[str, Any]] | None = None,
        state_writer: BridgeStateWriter | None = None,
    ) -> None:
        self.client = client
        self.endpoints = endpoints
        self.interval = max(1, interval)
        self.endpoints_factory = endpoints_factory
        self.state_writer = state_writer
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._registered = False
        # Consecutive failed register attempts, for exponential backoff on the
        # retry loop. Reset to 0 on any successful register.
        self._register_failures = 0
        self._max_register_backoff = _MAX_REGISTER_BACKOFF_SECONDS
        self._last_response: RegisterResponse | None = None
        # Tracks the manifest FleetQ currently knows about so the drift
        # check has something to compare against. Updated on successful
        # register and successful update_endpoints.
        self._last_pushed_endpoints: dict[str, Any] = endpoints

    @property
    def registered(self) -> bool:
        return self._registered

    @property
    def last_response(self) -> RegisterResponse | None:
        """Return the most recent successful RegisterResponse (if any).

        Used by the entry point to start a BridgeRelay subscriber once we
        have the reverb_app_key + reverb_relay_url + team_id.
        """
        return self._last_response

    def _register_now(self) -> None:
        try:
            response = self.client.register(self.endpoints)
            self._registered = True
            self._register_failures = 0
            self._last_response = response
            # The manifest we just sent is now the authoritative known state
            # on FleetQ — sync the drift baseline so the next factory tick
            # doesn't immediately re-issue update_endpoints.
            self._last_pushed_endpoints = self.endpoints
            logger.info(
                "FleetQ bridge registered: session=%s team=%s",
                response.session_id, response.team_id,
            )
            if self.state_writer is not None:
                self.state_writer.update(
                    connected=True,
                    team_id=response.team_id,
                    session_id=response.session_id,
                    last_error=None,
                )
        except BridgeError as e:
            self._registered = False
            self._register_failures += 1
            logger.warning(
                "FleetQ bridge register failed (attempt %d): %s — next retry in %ds",
                self._register_failures, e, int(self._register_retry_delay()),
            )
            if self.state_writer is not None:
                self.state_writer.mark_disconnected(error=str(e))

    def start(self) -> None:
        """Register synchronously (so auth failures surface to the caller),
        then spin up the heartbeat thread. Idempotent."""
        if self._thread and self._thread.is_alive():
            return
        self._register_now()
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name="fleetq-heartbeat"
        )
        self._thread.start()

    def stop(self) -> None:
        """Signal the heartbeat thread to exit, disconnect from FleetQ, and
        close the HTTP client. Safe to call multiple times."""
        self._stop.set()
        if self._registered:
            try:
                n = self.client.disconnect()
                logger.info("FleetQ bridge disconnected (n=%d)", n)
                self._registered = False
            except BridgeError as e:
                logger.warning("FleetQ bridge disconnect failed: %s", e)
        self.client.close()
        if self.state_writer is not None:
            self.state_writer.mark_disconnected()

    def _register_retry_delay(self) -> float:
        """Exponential backoff (capped) for the register-retry loop.

        Only meaningful while unregistered, i.e. ``_register_failures >= 1``.
        Doubles from ``interval`` per consecutive failure up to
        ``_max_register_backoff``. The exponent is clamped so ``2 ** exp``
        can't overflow into an absurd value before the cap applies.
        """
        exp = min(max(self._register_failures - 1, 0), 16)
        # `1 << exp` (== 2**exp; exp is clamped >= 0) keeps mypy's int typing;
        # `2 ** <non-literal>` widens to Any in typeshed.
        return min(self.interval * (1 << exp), self._max_register_backoff)

    def _loop(self) -> None:
        # When registered, tick at `interval`. While unregistered (initial or
        # session-loss re-register failing), back off exponentially so a
        # persistent auth failure doesn't retry every `interval` forever.
        while True:
            delay = (
                self.interval
                if self._registered
                else self._register_retry_delay()
            )
            if self._stop.wait(delay):
                return
            if not self._registered:
                # Register still failing; retry with escalating backoff.
                self._register_now()
                continue
            try:
                alive = self.client.heartbeat()
            except BridgeError as e:
                logger.warning("FleetQ bridge heartbeat failed: %s", e)
                if self.state_writer is not None:
                    self.state_writer.update(last_error=str(e))
                continue
            if not alive:
                # Session lost (FleetQ's detect-stale marked us Disconnected).
                # The heartbeat endpoint does NOT auto-revive on 404 — we have
                # to call register again with our same session_id.
                logger.info("FleetQ bridge session lost — re-registering")
                self._register_now()
                continue
            # Session is alive — refresh the heartbeat timestamp and clear
            # the prior error (if any) so the UI badge can flip back to green.
            if self.state_writer is not None:
                self.state_writer.update(connected=True, last_error=None)
            # Then check whether the manifest has drifted and re-publish if so.
            # Only runs when an endpoints_factory was set; otherwise the
            # static `self.endpoints` from construction stands.
            self._maybe_update_endpoints()

    def _maybe_update_endpoints(self) -> None:
        """If an endpoints_factory was configured, rebuild the manifest and
        push it to FleetQ when it differs from the last known-good state.

        Errors from the factory (e.g. a transient I/O hiccup while reading
        config) are logged and swallowed — the heartbeat must keep going.
        Errors from update_endpoints itself are also swallowed; the next
        tick will retry. The drift baseline is only advanced on success
        so we don't silently drop an update.
        """
        if self.endpoints_factory is None:
            return
        try:
            current = self.endpoints_factory()
        except Exception:
            logger.exception(
                "FleetQ endpoints_factory raised — skipping update_endpoints"
            )
            return
        if current == self._last_pushed_endpoints:
            return
        try:
            self.client.update_endpoints(current)
        except BridgeError as e:
            logger.warning("FleetQ bridge update_endpoints failed: %s", e)
            return
        self._last_pushed_endpoints = current
        self.endpoints = current
        logger.info("FleetQ bridge endpoints updated (drift detected)")

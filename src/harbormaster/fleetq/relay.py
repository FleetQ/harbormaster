"""FleetQ Bridge reverse-channel relay subscriber (Pusher path).

v1.0.0a8 scope: connect to Reverb, authenticate the private-daemon channel
via /api/v1/bridge/broadcasting-auth, subscribe, log received `agent.request`
events at INFO. NO execution dispatch — that's v1.0.0a9.

v2.0.0a7 adds the *publish* side: `BridgeRelay.publish_chunk()` and
`publish_error()` send Pusher client events back on the same channel
following the wire shape in `docs/fleetq-relay-protocol.md`. An optional
`chunk_handler: Callable[[dict], Iterator[str]]` can be wired into
`__init__`; when set, incoming `agent.request` events are dispatched to
the handler and its yielded text chunks stream back as
`client-relay.chunk` events (done=false per token, done=true final).
Exceptions in the handler become `client-relay.error` events.

The handler is deliberately narrow: it gets the agent.request payload
and returns an iterator of text chunks. Wiring agent.request → MCP
tool selection lives one layer up so that the relay stays pluggable
for non-MCP dispatch scenarios.

See docs/fleetq-relay-protocol.md for the discovered protocol.

Imports `pysher` lazily through a factory so test suites can inject a fake
Pusher and avoid a hard dependency on the [fleetq] extra in [dev].
"""
from __future__ import annotations

import json
import logging
from collections.abc import Callable, Iterator
from typing import Any
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)

# Type for the pusher_factory injection point: callable that returns
# something with `.connection.bind(event, handler)`, `.subscribe(channel, auth)`,
# `.connect()`, `.disconnect()`. Matches pysher.Pusher's surface.
PusherFactory = Callable[..., Any]

# Handler called when an `agent.request` arrives and chunk_handler was
# provided. Receives the parsed payload dict, yields text chunks. The
# relay handles publishing each chunk + the final done=true sentinel.
ChunkHandler = Callable[[dict[str, Any]], Iterator[str]]


def _default_pusher_factory(
    *,
    key: str,
    host: str,
    port: int,
    secure: bool,
) -> Any:
    """Lazy import — only triggered when the relay actually starts.

    pysher's `Pusher.__init__` exposes the WebSocket host parameter
    as `custom_host=`, NOT `host=`. Passing `host=` lands in pysher's
    `**thread_kwargs` and eventually reaches `Thread.__init__()`,
    which raises `TypeError: unexpected keyword argument 'host'`.
    Symptom: the FleetQ Reverb relay subscriber refused to start in
    every harbormaster-mcp invocation; bridge registered + heartbeat
    worked, but no inbound MCP calls from FleetQ were received.
    v2.0.1 regression fix.
    """
    import pysher

    return pysher.Pusher(key=key, custom_host=host, port=port, secure=secure)


class BridgeRelay:
    """Subscribes to FleetQ's private-daemon.<team_id> Reverb channel and
    logs incoming `agent.request` events. Stops on demand.

    Lifecycle:
        relay = BridgeRelay(
            base_url=..., api_token=..., team_id=...,
            app_key=..., relay_url="wss://app.fleetq.net:443",
        )
        relay.start()
        ...
        relay.stop()

    The actual Pusher connection runs in pysher's internal thread pool, so
    start() is non-blocking — it returns as soon as the connect call has
    been issued. Connection-established + subscription-confirmed happens
    asynchronously and is logged.
    """

    def __init__(
        self,
        *,
        base_url: str,
        api_token: str,
        team_id: str,
        app_key: str,
        relay_url: str,
        pusher_factory: PusherFactory | None = None,
        auth_timeout: float = 10.0,
        chunk_handler: ChunkHandler | None = None,
    ) -> None:
        if not team_id:
            raise ValueError("team_id is required (from RegisterResponse)")
        if not app_key:
            raise ValueError("app_key is required (from RegisterResponse.reverb)")
        if not relay_url:
            raise ValueError("relay_url is required (from RegisterResponse.reverb)")

        self.base_url = base_url.rstrip("/")
        self.api_token = api_token
        self.team_id = team_id
        self.app_key = app_key
        self.relay_url = relay_url
        self.channel_name = f"private-daemon.{team_id}"
        self.auth_timeout = auth_timeout
        self.chunk_handler = chunk_handler

        self._pusher_factory: PusherFactory = pusher_factory or _default_pusher_factory
        self._pusher: Any = None
        self._channel: Any = None
        self._socket_id: str | None = None
        self._subscribed: bool = False

    @property
    def subscribed(self) -> bool:
        return self._subscribed

    @property
    def socket_id(self) -> str | None:
        return self._socket_id

    def parse_relay_url(self) -> tuple[str, int, bool]:
        """Decompose wss://host:port into (host, port, secure) for pysher."""
        u = urlparse(self.relay_url)
        secure = u.scheme == "wss"
        port = u.port if u.port is not None else (443 if secure else 80)
        if not u.hostname:
            raise ValueError(f"relay_url missing hostname: {self.relay_url!r}")
        return u.hostname, port, secure

    def fetch_channel_auth(self, socket_id: str) -> str:
        """Call FleetQ's broadcasting-auth helper. Returns the `auth` string
        suitable for passing to pusher.subscribe(channel, auth=...)."""
        with httpx.Client(timeout=self.auth_timeout) as client:
            r = client.post(
                f"{self.base_url}/api/v1/bridge/broadcasting-auth",
                headers={
                    "Authorization": f"Bearer {self.api_token}",
                    "Accept": "application/json",
                },
                data={
                    "socket_id": socket_id,
                    "channel_name": self.channel_name,
                },
            )
        r.raise_for_status()
        body = r.json()
        auth = body.get("auth")
        if not isinstance(auth, str) or not auth:
            raise RuntimeError(
                f"broadcasting-auth returned unexpected body: {body}"
            )
        return auth

    def start(self) -> None:
        """Begin the Reverb connection + subscribe lifecycle.

        Non-blocking: returns once pysher's connect call has been issued.
        The connection-established → auth → subscribe flow happens in
        pysher's internal thread.
        """
        host, port, secure = self.parse_relay_url()
        logger.info(
            "BridgeRelay: connecting to Reverb at %s://%s:%d (channel=%s)",
            "wss" if secure else "ws", host, port, self.channel_name,
        )
        self._pusher = self._pusher_factory(
            key=self.app_key, host=host, port=port, secure=secure,
        )
        self._pusher.connection.bind(
            "pusher:connection_established", self._on_connection_established
        )
        self._pusher.connect()

    def stop(self) -> None:
        """Disconnect from Reverb. Idempotent."""
        if self._pusher is None:
            return
        try:
            self._pusher.disconnect()
        except Exception as e:  # noqa: BLE001 - best-effort cleanup
            logger.warning("BridgeRelay: disconnect raised %s", e)
        finally:
            self._pusher = None
            self._subscribed = False
            self._socket_id = None

    def _on_connection_established(self, data: str | dict[str, Any]) -> None:
        """Pusher fires this with the socket_id once the WS handshake completes."""
        try:
            payload = json.loads(data) if isinstance(data, str) else data
            socket_id = str(payload.get("socket_id", "") or "")
        except (TypeError, ValueError) as e:
            logger.error("BridgeRelay: malformed connection_established: %s", e)
            return
        if not socket_id:
            logger.error("BridgeRelay: connection_established without socket_id")
            return
        self._socket_id = socket_id
        logger.info("BridgeRelay: connected (socket_id=%s) — fetching channel auth", socket_id)

        try:
            auth = self.fetch_channel_auth(socket_id)
        except Exception as e:  # noqa: BLE001 - failure here is the auth boundary
            logger.error(
                "BridgeRelay: channel auth failed (%s) — events for %s will not arrive",
                e, self.channel_name,
            )
            return

        channel = self._pusher.subscribe(self.channel_name, auth=auth)
        self._channel = channel
        # 'agent.request' is the event class's broadcastAs() value.
        channel.bind("agent.request", self._on_agent_request)
        # pusher_internal:subscription_succeeded fires once subscription is confirmed.
        channel.bind("pusher_internal:subscription_succeeded", self._on_subscribed)
        logger.info(
            "BridgeRelay: subscription requested for %s",
            self.channel_name,
        )

    def _on_subscribed(self, _data: Any = None) -> None:
        self._subscribed = True
        logger.info(
            "BridgeRelay: subscribed to %s — listening for agent.request events",
            self.channel_name,
        )

    def _on_agent_request(self, data: str | dict[str, Any]) -> None:
        """Handle an inbound agent.request event.

        Logs the request unconditionally. When `chunk_handler` was wired
        at construction (v2.0.0a7), also dispatches the payload to the
        handler and streams its yielded text chunks back via
        `client-relay.chunk` events on the same channel. Final chunk has
        `done=true`. Exceptions become `client-relay.error`.
        """
        try:
            payload = json.loads(data) if isinstance(data, str) else data
        except (TypeError, ValueError):
            payload = {"raw": str(data)[:200]}
        if not isinstance(payload, dict):
            payload = {"raw": str(payload)[:200]}
        request_id = str(payload.get("request_id", "") or "")
        logger.info(
            "BridgeRelay: agent.request received "
            "(request_id=%s, method=%s, server=%s)",
            request_id or "?",
            payload.get("method", "?"),
            payload.get("server", "?"),
        )

        if self.chunk_handler is None:
            return
        if not request_id:
            logger.warning(
                "BridgeRelay: chunk_handler set but request_id missing in payload; "
                "cannot publish response — skipping dispatch."
            )
            return
        self._dispatch_chunk_handler(request_id=request_id, payload=payload)

    def _dispatch_chunk_handler(
        self, *, request_id: str, payload: dict[str, Any]
    ) -> None:
        """Run the configured chunk_handler and stream its output as
        client-relay.chunk events. Catches every exception so a buggy
        handler can't crash the Pusher thread; surfaces failure as
        `client-relay.error` so the FleetQ side can wake the waiting
        request with a sentinel.
        """
        assert self.chunk_handler is not None  # narrowed by caller
        try:
            iterator = self.chunk_handler(payload)
            chunk_count = 0
            for chunk in iterator:
                if not isinstance(chunk, str) or not chunk:
                    continue
                self.publish_chunk(
                    request_id=request_id, chunk=chunk, done=False
                )
                chunk_count += 1
            # Final sentinel chunk — empty payload + done=true terminates
            # the FleetQ-side popChunk loop cleanly.
            self.publish_chunk(request_id=request_id, chunk="", done=True)
            logger.info(
                "BridgeRelay: dispatched %d chunks for request_id=%s",
                chunk_count,
                request_id,
            )
        except Exception as e:  # noqa: BLE001 - handler is untrusted
            logger.exception(
                "BridgeRelay: chunk_handler raised for request_id=%s", request_id
            )
            try:
                self.publish_error(request_id=request_id, error=str(e))
            except Exception:  # noqa: BLE001 - cleanup must not raise
                logger.exception(
                    "BridgeRelay: publish_error also failed for request_id=%s",
                    request_id,
                )

    # --- v2.0.0a7 publish surface ---------------------------------------

    def publish_chunk(
        self, *, request_id: str, chunk: str, done: bool, usage: object | None = None
    ) -> None:
        """Send a `client-relay.chunk` Pusher client event on the
        subscribed channel. Wire shape from `docs/fleetq-relay-protocol.md`:

            { "request_id": <uuid>, "chunk": <str>, "done": <bool>, "usage": <obj|null> }

        Multi-chunk streams use `done=false` per token and a final
        empty-`chunk`/`done=true` sentinel to close the popChunk loop.
        """
        if self._channel is None:
            raise RuntimeError(
                "BridgeRelay: cannot publish_chunk before subscribe completes"
            )
        data = {
            "request_id": request_id,
            "chunk": chunk,
            "done": done,
            "usage": usage,
        }
        self._channel.trigger("client-relay.chunk", data)

    def publish_error(self, *, request_id: str, error: str) -> None:
        """Send a `client-relay.error` Pusher client event on the
        subscribed channel. Wire shape from `docs/fleetq-relay-protocol.md`:

            { "request_id": <uuid>, "error": <human-readable str> }

        Wakes the FleetQ-side popChunk loop with a sentinel and
        re-throws the error to the original mcpCall caller.
        """
        if self._channel is None:
            raise RuntimeError(
                "BridgeRelay: cannot publish_error before subscribe completes"
            )
        data = {"request_id": request_id, "error": error}
        self._channel.trigger("client-relay.error", data)

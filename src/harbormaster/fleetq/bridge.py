"""FleetQ Bridge HTTP client — register / heartbeat / update_endpoints / disconnect.

Sync httpx; runs from a background thread, no asyncio plumbing required.
Imports httpx eagerly because the parent harbormaster.fleetq package is the
gatekeeper for the [fleetq] extra — only loaded when integration is enabled.

Contract reference: docs/fleetq-bridge-contract.md.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from typing import Any

import httpx


@dataclass(frozen=True)
class RegisterResponse:
    """Successful response from POST /api/v1/bridge/register."""

    session_id: str
    team_id: str
    connected_at: str  # ISO-8601 from FleetQ
    reverb_app_key: str | None  # for the future reverse-channel; v1.0.0a6 ignores
    reverb_relay_url: str | None


class BridgeError(Exception):
    """Bridge HTTP failure (auth, network, server error, unexpected payload).

    Distinct from session-lost (heartbeat 404), which is signalled by
    BridgeClient.heartbeat() returning False — that's a recoverable state,
    not an error.
    """


def _make_session_id() -> str:
    """Convention: harbormaster-<short-uuid7>-<unix_ts>. Stale sessions
    are visually obvious in FleetQ's connections list."""
    return f"harbormaster-{uuid.uuid4().hex[:16]}-{int(time.time())}"


class BridgeClient:
    """Thin synchronous client for the FleetQ Bridge HTTP API.

    Stateful: holds the same `session_id` across register / heartbeat /
    update_endpoints / disconnect so the FleetQ side ties them together
    (heartbeats reference the registered session). Callers create one
    client per harbormaster process.
    """

    def __init__(
        self,
        *,
        base_url: str,
        api_token: str,
        label: str = "harbormaster",
        bridge_version: str = "0.0.0+unknown",
        session_id: str | None = None,
        timeout: float = 10.0,
    ) -> None:
        if not base_url:
            raise ValueError("base_url is required")
        if not api_token:
            raise ValueError("api_token is required")
        self.base_url = base_url.rstrip("/")
        self.api_token = api_token
        self.label = label
        self.bridge_version = bridge_version
        self.session_id = session_id or _make_session_id()
        self._client = httpx.Client(
            base_url=self.base_url,
            timeout=timeout,
            headers={
                "Authorization": f"Bearer {api_token}",
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
        )

    def register(self, endpoints: dict[str, Any]) -> RegisterResponse:
        """POST /api/v1/bridge/register. Upserts on FleetQ side."""
        payload = {
            "session_id": self.session_id,
            "bridge_version": self.bridge_version,
            "label": self.label,
            "endpoints": endpoints,
        }
        try:
            r = self._client.post("/api/v1/bridge/register", json=payload)
        except httpx.HTTPError as e:
            raise BridgeError(f"register: {type(e).__name__}: {e}") from e
        if r.status_code != 201:
            raise BridgeError(f"register: HTTP {r.status_code}: {r.text[:300]}")

        body = r.json().get("data", {})
        reverb = body.get("reverb") or {}
        return RegisterResponse(
            session_id=body.get("session_id", self.session_id),
            team_id=body.get("team_id", ""),
            connected_at=body.get("connected_at", ""),
            reverb_app_key=reverb.get("app_key"),
            reverb_relay_url=reverb.get("relay_url"),
        )

    def heartbeat(self) -> bool:
        """POST /api/v1/bridge/heartbeat.

        Returns True if the heartbeat was acknowledged (`alive: true`),
        False if FleetQ returned 404 — session lost, caller should call
        register() again with the same session_id to recover. All other
        non-200 responses raise BridgeError.
        """
        payload = {"session_id": self.session_id}
        try:
            r = self._client.post("/api/v1/bridge/heartbeat", json=payload)
        except httpx.HTTPError as e:
            raise BridgeError(f"heartbeat: {type(e).__name__}: {e}") from e
        if r.status_code == 404:
            return False
        if r.status_code != 200:
            raise BridgeError(f"heartbeat: HTTP {r.status_code}: {r.text[:300]}")
        return True

    def update_endpoints(self, endpoints: dict[str, Any]) -> None:
        """POST /api/v1/bridge/endpoints — refresh the discovered manifest."""
        payload = {"session_id": self.session_id, "endpoints": endpoints}
        try:
            r = self._client.post("/api/v1/bridge/endpoints", json=payload)
        except httpx.HTTPError as e:
            raise BridgeError(f"update_endpoints: {type(e).__name__}: {e}") from e
        if r.status_code != 200:
            raise BridgeError(f"update_endpoints: HTTP {r.status_code}: {r.text[:300]}")

    def disconnect(self) -> int:
        """DELETE /api/v1/bridge/. Returns the number of disconnected
        connections (0 means our session was already stale — idempotent)."""
        payload = {"session_id": self.session_id}
        try:
            r = self._client.request("DELETE", "/api/v1/bridge/", json=payload)
        except httpx.HTTPError as e:
            raise BridgeError(f"disconnect: {type(e).__name__}: {e}") from e
        if r.status_code == 404:
            return 0
        if r.status_code != 200:
            raise BridgeError(f"disconnect: HTTP {r.status_code}: {r.text[:300]}")
        return int(r.json().get("data", {}).get("disconnected", 0))

    def close(self) -> None:
        """Release the underlying httpx connection pool."""
        self._client.close()

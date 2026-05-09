"""FleetQ Memory writeback — opt-in trajectory persistence.

After every successful ask_project / delegate_task call, post the
question + answer to FleetQ's `/api/v1/memory` endpoint so the
trajectory becomes searchable across the user's full project fleet.

Opt-in via `[fleetq] write_trajectories = true` (the default once
[fleetq] is enabled). Writeback failures NEVER fail the originating
tool call — they're best-effort and logged.
"""
from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class MemoryWriter:
    """Sync httpx client for FleetQ Memory writeback.

    Constructed once per harbormaster process and reused across calls.
    The MCP tool surface is small (handful of tools, low call rate per
    user) so a single shared HTTP client without async coordination is
    plenty.
    """

    def __init__(
        self,
        *,
        base_url: str,
        api_token: str,
        timeout: float = 5.0,
    ) -> None:
        if not base_url:
            raise ValueError("base_url is required")
        if not api_token:
            raise ValueError("api_token is required")
        self.base_url = base_url.rstrip("/")
        self._client = httpx.Client(
            base_url=self.base_url,
            timeout=timeout,
            headers={
                "Authorization": f"Bearer {api_token}",
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
        )

    def write_trajectory(
        self,
        *,
        project_name: str,
        host: str | None,
        question: str,
        answer: str,
        tool: str = "ask_project",
        metadata: dict[str, Any] | None = None,
    ) -> bool:
        """Post one trajectory. Returns True on success, False (with a
        logged warning) on any failure — including network errors,
        non-2xx responses, or invalid JSON in the response.

        Failure to write back MUST NOT propagate; the caller's
        response is already in flight.
        """
        payload: dict[str, Any] = {
            "type": "trajectory",
            "tool": tool,
            "project": project_name,
            "host": host or "local",
            "content": {
                "question": question,
                "answer": answer,
            },
        }
        if metadata:
            payload["metadata"] = metadata

        try:
            r = self._client.post("/api/v1/memory", json=payload)
        except httpx.HTTPError as e:
            logger.warning(
                "FleetQ memory writeback failed (network): %s: %s",
                type(e).__name__, e,
            )
            return False

        if r.status_code >= 400:
            logger.warning(
                "FleetQ memory writeback rejected: HTTP %d: %s",
                r.status_code, r.text[:300],
            )
            return False

        return True

    def close(self) -> None:
        """Release the underlying httpx connection pool."""
        self._client.close()

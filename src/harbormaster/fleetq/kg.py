"""FleetQ KnowledgeGraph writer (v1.2 phase 2).

Posts entity-relation triples to FleetQ `/api/v1/memory` with a
`type: "kg_triple"` discriminator. Extends the existing Memory
endpoint rather than introducing a new one — minimum coordination
with the FleetQ side. The discriminator gives FleetQ a clear
classifier when it later separates trajectories from triples into
distinct domains.

Mirrors `harbormaster.fleetq.memory.MemoryWriter`:
  * Constructed once per harbormaster process, reused across calls.
  * Sync httpx client; the call rate is too low to need async.
  * Returns False (with a logged warning) on any failure.
  * Failure NEVER propagates — the user's MCP response is already
    being prepared by the time the writer fires.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import httpx

logger = logging.getLogger("harbormaster.fleetq.kg")


@dataclass(frozen=True)
class Triple:
    """One subject—predicate—object triple.

    Note: the RDF-canonical name for the third position is "object",
    but Python's `object` is a builtin type and using it as a field
    name confuses mypy. We store the value under `obj` and rename it
    to `"object"` in the wire payload via `as_dict()` so the FleetQ
    side sees the canonical key.
    """

    subject: str          # canonical project name on this harbormaster
    predicate: str        # the relation (uses, exposes, mentions, calls, ...)
    obj: str              # the other side of the relation (RDF "object")
    confidence: float = 1.0  # 0..1 — heuristic extractors set < 1.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "subject": self.subject,
            "predicate": self.predicate,
            "object": self.obj,
            "confidence": self.confidence,
        }


class KGWriter:
    """Sync httpx client for FleetQ KG writeback.

    The wire shape extends `/api/v1/memory` with `type: "kg_triple"`
    so the FleetQ side can be added incrementally without a new
    endpoint. Until FleetQ ships KG-aware processing, posts are
    accepted by Memory and stored as opaque records — still useful as
    durable history we can later replay.
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

    def write_triple(
        self,
        *,
        triple: Triple,
        project_name: str,
        host: str | None,
        source_tool: str = "ask_project",
        metadata: dict[str, Any] | None = None,
    ) -> bool:
        """Post one triple. Returns True on success, False (with a
        logged warning) on any failure.

        FleetQ accepts the payload via the same /api/v1/memory endpoint
        that takes trajectories — the `type` discriminator distinguishes
        them. Any failure is logged at WARNING and never propagates.
        """
        payload: dict[str, Any] = {
            "type": "kg_triple",
            "tool": source_tool,
            "project": project_name,
            "host": host or "local",
            "content": triple.as_dict(),
        }
        if metadata:
            payload["metadata"] = metadata

        try:
            r = self._client.post("/api/v1/memory", json=payload)
        except httpx.HTTPError as e:
            logger.warning(
                "FleetQ KG writeback failed (network): %s: %s",
                type(e).__name__, e,
            )
            return False

        if r.status_code >= 400:
            logger.warning(
                "FleetQ KG writeback rejected: HTTP %d: %s",
                r.status_code, r.text[:300],
            )
            return False

        return True

    def write_triples(
        self,
        *,
        triples: list[Triple],
        project_name: str,
        host: str | None,
        source_tool: str = "ask_project",
        metadata: dict[str, Any] | None = None,
    ) -> int:
        """Post many triples. Returns the count successfully posted.
        Continues past individual failures so a single bad triple
        doesn't blackhole the rest of the batch."""
        ok_count = 0
        for triple in triples:
            if self.write_triple(
                triple=triple,
                project_name=project_name,
                host=host,
                source_tool=source_tool,
                metadata=metadata,
            ):
                ok_count += 1
        return ok_count

    def close(self) -> None:
        """Release the underlying httpx connection pool."""
        self._client.close()

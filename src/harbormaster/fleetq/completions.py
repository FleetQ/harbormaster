"""FleetQ Bridge completion-event publisher (v24.0.0a7).

Reverses the channel the FleetQ-Bridge sub-agent delivered: when a
JobStore.complete() / fail() fires, this module POSTs a JSON payload
to the relay's ``/api/v1/harbormaster/job-completed`` endpoint, which
then broadcasts to ``private-harbormaster.{team_id}`` on Pusher.

Wired as a ``JobStore`` subscriber via ``get_subsystem`` when
``[fleetq] publish_completions = true`` AND ``team_id`` is set AND
``api_token_env`` resolves a non-empty value.

Failures are logged + swallowed — instrumentation must never break
the JobStore worker (pattern from v21.0.6 + v21.0.7). The relay
itself trims output/error to 1000 chars on the wire; harbormaster
ships full payloads and lets the bridge decide.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import urllib.error
import urllib.request

from harbormaster.config import HarbormasterConfig
from harbormaster.jobs.store import Job

_LOG = logging.getLogger(__name__)


class CompletionPublisher:
    """Stateless-ish POST-on-completion bridge between JobStore and
    fleetq-bridge's harbormaster channel.

    Stateless contract: every call rebuilds the payload from the
    ``Job`` plus current config; no in-memory queue. If FleetQ is
    unreachable, the event is logged + dropped (the SSE channel and
    the JobStore row both still capture it for replay).
    """

    def __init__(self, config: HarbormasterConfig) -> None:
        self._config = config
        # Snapshot at construction — env tokens can rotate but
        # in-process changes don't need live reload for the v24
        # surface.
        self._endpoint = (
            config.fleetq.base_url.rstrip("/")
            + "/api/v1/harbormaster/job-completed"
        )
        self._team_id = config.fleetq.team_id
        self._token = os.environ.get(config.fleetq.api_token_env, "")
        self._timeout = 5.0

    def is_armed(self) -> bool:
        """Return True iff all three preconditions are met:
        publish_completions, team_id, token. Same three-gate shape
        as the v16 FleetQ writeback (``_maybe_writeback_to_fleetq``).
        """
        return (
            self._config.fleetq.publish_completions
            and bool(self._team_id)
            and bool(self._token)
        )

    def publish(self, job: Job) -> None:
        """Subscriber-callback signature: ``Callable[[Job], None]``.

        Wired into ``JobStore.add_subscriber`` by the subsystem.
        Runs on the JobWorker thread (post-complete/fail). Exception-
        suppressed at the JobStore boundary so a relay outage doesn't
        kill the worker.
        """
        if not self.is_armed():
            return  # not configured — silent no-op
        if job.status not in ("completed", "failed"):
            return  # only terminal events
        payload = _build_payload(job, self._team_id)
        # Off-thread POST so we never block the worker — even a fast
        # 200 response can add 50-100ms over the loopback / network,
        # which would back up the queue under high job throughput.
        t = threading.Thread(
            target=self._post,
            args=(payload,),
            name=f"harbormaster.fleetq.publish.{job.id}",
            daemon=True,
        )
        t.start()

    def _post(self, payload: dict[str, object]) -> None:
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            self._endpoint,
            data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self._token}",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                status = resp.status
            if status not in (200, 202):
                _LOG.warning(
                    "fleetq completion publish: unexpected HTTP %d "
                    "from %s", status, self._endpoint,
                )
        except urllib.error.HTTPError as e:
            _LOG.warning(
                "fleetq completion publish: HTTP %d (%s) — dropping event",
                e.code, e.reason,
            )
        except (TimeoutError, urllib.error.URLError, OSError) as e:
            _LOG.warning(
                "fleetq completion publish: network error %r — dropping event",
                e,
            )


def _build_payload(job: Job, team_id: str) -> dict[str, object]:
    """Match the fleetq-bridge JobCompletedPayload contract verbatim
    (per their delivery report)."""
    return {
        "job_id": job.id,
        "team_id": team_id,
        "project": job.project,
        "host": job.host,
        "task": job.task[:2000],
        "deliverable": job.deliverable[:1000],
        "allow_writes": job.allow_writes,
        "status": job.status,
        "output": (job.output[:4000] if job.output else None),
        "error": (job.error[:4000] if job.error else None),
        "cid": job.cid,
        "queued_at": job.queued_at,
        "completed_at": job.completed_at,
        "duration_ms": job.duration_ms,
        "model": job.model,
        "max_turns": job.max_turns,
        "inbox_id": job.inbox_id,
    }

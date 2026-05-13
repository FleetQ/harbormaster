"""Background worker that picks ``queued`` jobs and dispatches them
through :func:`harbormaster.tools._helpers.run_backend` (v22.0.0a2).

The worker is a daemon thread — single-concurrency for v22.0.0a2 to
keep the failure mode obvious. Increase concurrency by spawning multiple
:class:`JobWorker` instances against the same :class:`JobStore`; the
``claim_next_queued`` UPDATE ... RETURNING is atomic so they will not
process the same row twice.

Worker lifecycle is owned by :mod:`harbormaster.jobs.subsystem`. Tools
never instantiate ``JobWorker`` directly.
"""
from __future__ import annotations

import logging
import threading
import time

from harbormaster.config import HarbormasterConfig
from harbormaster.jobs.store import Job, JobStore
from harbormaster.tools._grounding import build_grounded_prompt
from harbormaster.tools._helpers import run_backend

_LOG = logging.getLogger(__name__)

_READ_ONLY_SUFFIX = (
    "Read-only mode. Do NOT edit files. "
    "Report what you would do and which files you would touch. "
    "Return markdown under 500 words."
)

_WRITES_SUFFIX = (
    "You may edit files in this project. Make the change directly, "
    "then return a markdown summary under 500 words listing: "
    "(1) files changed with one-line reasons, "
    "(2) any new tests added, "
    "(3) follow-ups left for the operator. "
    "Do NOT git commit — the operator will review and commit."
)

_WRITES_AUTO_COMMIT_SUFFIX = (
    "You may edit files in this project. Make the change directly, "
    "run any relevant tests to validate, then git commit the changes "
    "with a clear conventional-commit message ('feat:', 'fix:', "
    "'refactor:' etc.). Do NOT push — the operator pushes after "
    "review. Return a markdown summary under 500 words listing: "
    "(1) files changed with one-line reasons, "
    "(2) any new tests added, "
    "(3) the commit SHA + subject, "
    "(4) follow-ups left for the operator."
)


def build_async_delegate_prompt(job: Job, config: HarbormasterConfig) -> str:
    """Build the prompt for an async delegated job.

    Mirrors ``tools/delegate.py``'s synchronous path so a sync and an
    async call to the same project produce the same shape of work.
    """
    grounded = build_grounded_prompt(
        question=f"{job.task}\n\nDeliverable: {job.deliverable}",
        project=job.project,
        host=job.host,
        config=config,
    )
    if job.allow_writes:
        suffix = (
            _WRITES_AUTO_COMMIT_SUFFIX if job.auto_commit else _WRITES_SUFFIX
        )
    else:
        suffix = _READ_ONLY_SUFFIX
    return f"{grounded}\n\n{suffix}"


class JobWorker:
    def __init__(
        self,
        *,
        config: HarbormasterConfig,
        store: JobStore,
        poll_interval_s: float = 0.5,
    ):
        self._config = config
        self._store = store
        self._poll_interval = poll_interval_s
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._loop,
            name="harbormaster.jobs.worker",
            daemon=True,
        )
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)

    def _loop(self) -> None:
        _LOG.info("delegate-job worker started")
        while not self._stop.is_set():
            job = self._store.claim_next_queued()
            if job is None:
                # Nothing queued — sleep briefly so we don't busy-loop.
                self._stop.wait(self._poll_interval)
                continue
            self._execute(job)
        _LOG.info("delegate-job worker stopped")

    def _execute(self, job: Job) -> None:
        start = time.monotonic()
        try:
            prompt = build_async_delegate_prompt(job, self._config)
            result = run_backend(
                name=job.project,
                prompt=prompt,
                max_turns=job.max_turns,
                host=job.host,
                config=self._config,
                label_prefix="delegate.async",
                model=job.model,
            )
        except Exception as exc:  # pragma: no cover — run_backend swallows
            # run_backend already converts BackendError → "Error: ..."
            # string; the only way this except fires is an unexpected
            # crash inside helpers. Treat it as a failure with no cid.
            duration_ms = int((time.monotonic() - start) * 1000)
            _LOG.exception("delegate-job %s unexpected crash", job.id)
            self._store.fail(
                job.id, error=f"unexpected: {exc!r}",
                cid=None, duration_ms=duration_ms,
            )
            return

        duration_ms = int((time.monotonic() - start) * 1000)
        if result.startswith("Error:"):
            # run_backend's failure shape includes the cid in brackets.
            # We keep the full string in `error` and try to extract the
            # cid so the inbox / get_delegated_task surfaces match the
            # sync-call error format.
            cid = _extract_cid(result)
            self._store.fail(
                job.id, error=result, cid=cid, duration_ms=duration_ms,
            )
        else:
            self._store.complete(
                job.id, output=result, duration_ms=duration_ms,
            )


def _extract_cid(error_string: str) -> str | None:
    """Pull the ``[cid=<hex>]`` token out of run_backend's failure
    string; returns ``None`` if the string isn't shaped that way (e.g.
    pre-v21.0.7 error format, or a validation failure that never
    minted a cid)."""
    marker = "[cid="
    start = error_string.find(marker)
    if start == -1:
        return None
    start += len(marker)
    end = error_string.find("]", start)
    if end == -1:
        return None
    return error_string[start:end]

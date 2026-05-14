"""Thread-safe SQLite store for async delegated jobs (v22.0.0a2)."""
from __future__ import annotations

import contextlib
import secrets
import sqlite3
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from harbormaster.jobs.schema import (
    CLARIFICATION_SCHEMA,
    MIGRATIONS,
    SCHEMA,
    STATUS_AWAITING_CALLER,
    STATUS_CLR_ANSWERED,
    STATUS_CLR_PENDING,
    STATUS_COMPLETED,
    STATUS_FAILED,
    STATUS_QUEUED,
    STATUS_RUNNING,
)


@dataclass(frozen=True)
class Job:
    """Typed view over one ``delegated_jobs`` row."""

    id: str
    inbox_id: str
    project: str
    host: str | None
    task: str
    deliverable: str
    allow_writes: bool
    model: str | None
    status: str
    output: str | None
    error: str | None
    cid: str | None
    queued_at: float
    started_at: float | None
    completed_at: float | None
    duration_ms: int | None
    read_at: float | None
    max_turns: int = 10
    auto_commit: bool = False
    # v26.0.0 — execution provenance + caller-reported usage.
    execution_mode: str = "subprocess"
    tokens_used: int | None = None
    rendered_prompt: str | None = None

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable view (booleans normalised, no nulls
        for keys callers always expect)."""
        return {
            "job_id": self.id,
            "inbox_id": self.inbox_id,
            "project": self.project,
            "host": self.host,
            "task": self.task,
            "deliverable": self.deliverable,
            "allow_writes": self.allow_writes,
            "model": self.model,
            "status": self.status,
            "output": self.output,
            "error": self.error,
            "cid": self.cid,
            "queued_at": self.queued_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "duration_ms": self.duration_ms,
            "read_at": self.read_at,
            "max_turns": self.max_turns,
            "auto_commit": self.auto_commit,
            "execution_mode": self.execution_mode,
            "tokens_used": self.tokens_used,
            "rendered_prompt": self.rendered_prompt,
        }


def _row_to_job(row: sqlite3.Row) -> Job:
    # v26.0.0 — execution_mode + tokens_used arrived via idempotent
    # ALTER TABLE migrations. Use dict access guarded by `.keys()` so
    # tests using mock rows (or pre-migration DBs surfaced through
    # legacy fixtures) don't crash.
    row_keys = set(row.keys())
    return Job(
        id=row["id"],
        inbox_id=row["inbox_id"],
        project=row["project"],
        host=row["host"],
        task=row["task"],
        deliverable=row["deliverable"],
        allow_writes=bool(row["allow_writes"]),
        model=row["model"],
        status=row["status"],
        output=row["output"],
        error=row["error"],
        cid=row["cid"],
        queued_at=row["queued_at"],
        started_at=row["started_at"],
        completed_at=row["completed_at"],
        duration_ms=row["duration_ms"],
        read_at=row["read_at"],
        max_turns=row["max_turns"],
        auto_commit=bool(row["auto_commit"]),
        execution_mode=(
            row["execution_mode"] if "execution_mode" in row_keys else "subprocess"
        ),
        tokens_used=(row["tokens_used"] if "tokens_used" in row_keys else None),
        rendered_prompt=(
            row["rendered_prompt"] if "rendered_prompt" in row_keys else None
        ),
    )


@dataclass(frozen=True)
class Clarification:
    """Typed view over one ``job_clarifications`` row."""

    id: str
    job_id: str
    question: str
    answer: str | None
    status: str  # pending | answered | timed_out
    asked_at: float
    answered_at: float | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "clarification_id": self.id,
            "job_id": self.job_id,
            "question": self.question,
            "answer": self.answer,
            "status": self.status,
            "asked_at": self.asked_at,
            "answered_at": self.answered_at,
        }


def _row_to_clarification(row: sqlite3.Row) -> Clarification:
    return Clarification(
        id=row["id"],
        job_id=row["job_id"],
        question=row["question"],
        answer=row["answer"],
        status=row["status"],
        asked_at=row["asked_at"],
        answered_at=row["answered_at"],
    )


class JobStore:
    """SQLite-backed store for async delegate jobs.

    Single connection guarded by ``threading.Lock`` — sqlite3 with WAL
    is fine for the modest write rate expected here (one
    enqueue + one complete per delegated call). The worker thread,
    enqueue calls from MCP tool handlers, and ``recall_pending_results``
    reads all share the lock to keep the contract simple.

    Use :func:`harbormaster.jobs.get_subsystem` rather than instantiating
    directly so callers share one store + one worker per process.
    """

    def __init__(self, db_path: Path):
        self._path = db_path
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(
            str(db_path), check_same_thread=False, isolation_level=None,
        )
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode = WAL")
        self._conn.execute("PRAGMA synchronous = NORMAL")
        self._conn.executescript(SCHEMA)
        self._conn.executescript(CLARIFICATION_SCHEMA)
        self._lock = threading.Lock()
        # v22.1.0: blocking-await primitives. Per-job ``Event`` so a
        # waiter on a specific id wakes on that id's completion; per-
        # inbox ``Condition`` so a waiter on an inbox wakes when ANY
        # job in that inbox lands. Lazily created — no event/condition
        # exists until either a waiter asks for one (via the wait_for
        # methods) or a completion fires (via _fire_completion).
        self._job_events: dict[str, threading.Event] = {}
        self._inbox_conditions: dict[str, threading.Condition] = {}
        # v22.2.0 hook: subscribers callable on every job state change.
        # Currently unused by JobStore; the resource-subscription
        # surface (v22.2.0) registers a callback here.
        self._subscribers: list[Callable[[Job], None]] = []
        # v25.0.0: clarification primitives. Per-clarification Event so
        # request_clarification() blocks until answered; per-job Condition
        # so await_clarification_request() wakes when any question arrives.
        self._clarification_events: dict[str, threading.Event] = {}
        self._job_clarification_conditions: dict[str, threading.Condition] = {}
        self._apply_migrations()

    def _apply_migrations(self) -> None:
        """v22.0.1: idempotently ``ALTER TABLE ADD COLUMN`` for any
        entry in ``MIGRATIONS`` not already present. Pattern carried
        over from v21.0.8's ``network_log.db`` — PRAGMA table_info
        names every existing column, ALTER TABLE ADD only the missing
        ones.

        Schema-only migrations (column adds with simple defaults) are
        the only shape supported here. Anything that needs a data
        backfill belongs in an explicit one-shot helper.
        """
        with self._lock:
            existing = {
                row["name"] for row in self._conn.execute(
                    "PRAGMA table_info(delegated_jobs)",
                ).fetchall()
            }
            for name, ddl in MIGRATIONS:
                if name not in existing:
                    self._conn.execute(
                        f"ALTER TABLE delegated_jobs ADD COLUMN {ddl}",
                    )

    @staticmethod
    def _new_job_id() -> str:
        return "d_" + secrets.token_hex(6)

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def enqueue(
        self,
        *,
        project: str,
        host: str | None,
        task: str,
        deliverable: str,
        allow_writes: bool,
        model: str | None,
        inbox_id: str = "default",
        max_turns: int = 10,
        auto_commit: bool = False,
        execution_mode: str = "subprocess",
        initial_status: str = STATUS_QUEUED,
        rendered_prompt: str | None = None,
    ) -> Job:
        """Insert a row and return its typed view.

        ``execution_mode`` (v26.0.0) records who runs the job. Default
        ``"subprocess"`` matches the v22-25 contract: ``initial_status``
        defaults to ``queued`` so a JobWorker picks it up. For
        instruction mode, callers pass ``execution_mode="instruction"``
        plus ``initial_status="awaiting_caller"`` — that row is invisible
        to workers (they only claim ``queued``) and waits for the MCP
        client to invoke ``record_delegation_result``.

        ``rendered_prompt`` (v26.0.0) is the full grounded + suffixed
        prompt persisted for instruction-mode rows so a caller who
        loses the original packet response can recover it faithfully
        via ``get_delegated_task``. NULL for subprocess rows — the
        worker builds its own prompt at run time.

        ``max_turns`` (v22.0.1) is the per-job turn budget the worker
        passes to ``run_backend``. ``auto_commit`` (v24.0.0a2)
        instructs the subagent to git-commit after edits — only
        meaningful when ``allow_writes=True``.
        """
        job_id = self._new_job_id()
        now = time.time()
        with self._lock:
            self._conn.execute(
                "INSERT INTO delegated_jobs ("
                "id, inbox_id, project, host, task, deliverable, "
                "allow_writes, model, status, queued_at, max_turns, "
                "auto_commit, execution_mode, rendered_prompt"
                ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    job_id, inbox_id, project, host, task, deliverable,
                    1 if allow_writes else 0, model, initial_status, now,
                    max_turns, 1 if auto_commit else 0, execution_mode,
                    rendered_prompt,
                ),
            )
        job = self.get(job_id)
        if job is None:  # pragma: no cover — we just inserted it
            raise RuntimeError(f"enqueued job {job_id} disappeared")
        return job

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM delegated_jobs WHERE id = ?", (job_id,),
            ).fetchone()
        return _row_to_job(row) if row else None

    def claim_next_queued(self) -> Job | None:
        """Atomically pick the oldest ``queued`` row and mark it
        ``running``. Returns ``None`` if nothing is queued.

        The UPDATE ... RETURNING form is used so the read-then-write
        races nobody — between SELECT and UPDATE there is no window.
        """
        now = time.time()
        with self._lock:
            row = self._conn.execute(
                "UPDATE delegated_jobs SET status = ?, started_at = ? "
                "WHERE id = ("
                "  SELECT id FROM delegated_jobs WHERE status = ? "
                "  ORDER BY queued_at ASC LIMIT 1"
                ") "
                "RETURNING *",
                (STATUS_RUNNING, now, STATUS_QUEUED),
            ).fetchone()
        return _row_to_job(row) if row else None

    def complete(
        self,
        job_id: str,
        *,
        output: str,
        duration_ms: int,
        tokens_used: int | None = None,
        expected_status: str | None = None,
    ) -> bool:
        """Mark ``job_id`` completed. v26.0.0 added ``tokens_used`` so
        instruction-mode callers can report cumulative token cost back,
        and ``expected_status`` so callers can require the row to be in
        a specific state before transitioning — closes the
        record_delegation_result TOCTOU window between read and update.

        Returns ``True`` when the row was actually updated and the
        completion fan-out fired; ``False`` when the optimistic guard
        rejected the transition (row was already terminal or moved on).
        """
        now = time.time()
        with self._lock:
            if expected_status is None:
                cur = self._conn.execute(
                    "UPDATE delegated_jobs "
                    "SET status = ?, output = ?, completed_at = ?, "
                    "    duration_ms = ?, tokens_used = ? "
                    "WHERE id = ?",
                    (
                        STATUS_COMPLETED, output, now, duration_ms,
                        tokens_used, job_id,
                    ),
                )
            else:
                cur = self._conn.execute(
                    "UPDATE delegated_jobs "
                    "SET status = ?, output = ?, completed_at = ?, "
                    "    duration_ms = ?, tokens_used = ? "
                    "WHERE id = ? AND status = ?",
                    (
                        STATUS_COMPLETED, output, now, duration_ms,
                        tokens_used, job_id, expected_status,
                    ),
                )
            updated = cur.rowcount > 0
        if updated:
            self._fire_completion(job_id)
        return updated

    def fail(
        self,
        job_id: str,
        *,
        error: str,
        cid: str | None,
        duration_ms: int,
        tokens_used: int | None = None,
        expected_status: str | None = None,
    ) -> bool:
        """Mark ``job_id`` failed. v26.0.0 added ``tokens_used`` for the
        instruction-mode contract: a caller may have spent tokens before
        the Agent failed; we record that cost honestly. ``expected_status``
        provides the same optimistic-CAS guard as ``complete()``.

        Returns ``True`` when the row was actually updated and the
        completion fan-out fired; ``False`` otherwise.
        """
        now = time.time()
        with self._lock:
            if expected_status is None:
                cur = self._conn.execute(
                    "UPDATE delegated_jobs "
                    "SET status = ?, error = ?, cid = ?, "
                    "    completed_at = ?, duration_ms = ?, tokens_used = ? "
                    "WHERE id = ?",
                    (
                        STATUS_FAILED, error, cid, now, duration_ms,
                        tokens_used, job_id,
                    ),
                )
            else:
                cur = self._conn.execute(
                    "UPDATE delegated_jobs "
                    "SET status = ?, error = ?, cid = ?, "
                    "    completed_at = ?, duration_ms = ?, tokens_used = ? "
                    "WHERE id = ? AND status = ?",
                    (
                        STATUS_FAILED, error, cid, now, duration_ms,
                        tokens_used, job_id, expected_status,
                    ),
                )
            updated = cur.rowcount > 0
        if updated:
            self._fire_completion(job_id)
        return updated

    def _fire_completion(self, job_id: str) -> None:
        """v22.1.0: wake any waiters parked on this job's Event or
        its inbox's Condition. Also (v22.2.0) invokes registered
        subscribers with the final ``Job`` view. Side-effects only —
        called from ``complete()`` and ``fail()`` after the SQL update
        commits.
        """
        job = self.get(job_id)
        if job is None:  # pragma: no cover — we just wrote the row
            return
        # Per-job Event: sticky one-shot, so order doesn't matter —
        # ``Event.wait()`` returns immediately if set before the wait.
        with self._lock:
            ev = self._job_events.get(job_id)
            cond = self._inbox_conditions.get(job.inbox_id)
            clr_cond = self._job_clarification_conditions.get(job_id)
            subs = list(self._subscribers)
        if ev is not None:
            ev.set()
        if cond is not None:
            with cond:
                cond.notify_all()
        # Wake any await_clarification_request blocked on this job so it
        # doesn't hang if the subagent finishes without asking anything.
        if clr_cond is not None:
            with clr_cond:
                clr_cond.notify_all()
        # Subscribers run outside the JobStore lock; any exception
        # they raise is swallowed (instrumentation must never break
        # the hot path — pattern from v21.0.6 + v21.0.7).
        for sub in subs:
            with contextlib.suppress(Exception):  # pragma: no cover — defensive
                sub(job)

    def add_subscriber(self, callback: Callable[[Job], None]) -> None:
        """v22.2.0: register a callable invoked on every job
        completion/failure with the final ``Job`` view. Subscribers
        run on the worker thread that completed the job, AFTER all
        blocking waiters have been notified.

        Idempotent only by identity — call once per subscriber.
        """
        with self._lock:
            if callback not in self._subscribers:
                self._subscribers.append(callback)

    def remove_subscriber(self, callback: Callable[[Job], None]) -> None:
        with self._lock, contextlib.suppress(ValueError):
            self._subscribers.remove(callback)

    def wait_for_job(
        self, job_id: str, *, timeout_seconds: float,
    ) -> Job | None:
        """v22.1.0: block until ``job_id`` completes or fails or
        ``timeout_seconds`` elapses.

        Returns the current ``Job`` either way — caller checks
        ``status`` to distinguish "completed within window" from
        "still running at timeout". Returns ``None`` if the job_id
        does not exist.

        Fast-path: returns immediately if the job is already in a
        terminal state when called.
        """
        job = self.get(job_id)
        if job is None:
            return None
        if job.status in (STATUS_COMPLETED, STATUS_FAILED):
            return job
        with self._lock:
            ev = self._job_events.get(job_id)
            if ev is None:
                ev = threading.Event()
                self._job_events[job_id] = ev
        # Second check: _fire_completion may have run in the window between
        # the first status read above and event registration. If the job is
        # already terminal we return immediately; otherwise ev is guaranteed
        # to be set by _fire_completion before or after ev.wait() below
        # (Events are sticky, so a pre-wait set still wakes the caller).
        job = self.get(job_id)
        if job is not None and job.status in (STATUS_COMPLETED, STATUS_FAILED):
            return job
        ev.wait(timeout=timeout_seconds)
        return self.get(job_id)

    def wait_for_inbox(
        self,
        inbox_id: str,
        *,
        timeout_seconds: float,
        since: float | None = None,
    ) -> list[Job]:
        """v22.1.0: block until at least one job in ``inbox_id`` lands
        in a terminal state, or ``timeout_seconds`` elapses.

        ``since`` (unix seconds, optional) filters out completions the
        caller has already seen — pass the largest ``completed_at``
        from the previous batch. ``None`` means "any unread terminal
        job in the inbox".

        Returns the unread terminal jobs. Empty list on timeout. The
        condition is acquired BEFORE the initial pending check to
        close the race where a job completes between check and wait.
        """
        cond = self._get_or_create_inbox_condition(inbox_id)

        def _matching() -> list[Job]:
            jobs = self.list_pending_for_inbox(inbox_id)
            if since is not None:
                jobs = [
                    j for j in jobs
                    if j.completed_at is not None and j.completed_at > since
                ]
            return jobs

        with cond:
            existing = _matching()
            if existing:
                return existing
            cond.wait(timeout=timeout_seconds)
        return _matching()

    def _get_or_create_inbox_condition(
        self, inbox_id: str,
    ) -> threading.Condition:
        with self._lock:
            cond = self._inbox_conditions.get(inbox_id)
            if cond is None:
                cond = threading.Condition()
                self._inbox_conditions[inbox_id] = cond
            return cond

    # ------------------------------------------------------------------
    # v25.0.0 clarification primitives
    # ------------------------------------------------------------------

    def _get_or_create_job_clarification_condition(
        self, job_id: str,
    ) -> threading.Condition:
        with self._lock:
            cond = self._job_clarification_conditions.get(job_id)
            if cond is None:
                cond = threading.Condition()
                self._job_clarification_conditions[job_id] = cond
            return cond

    def add_clarification(self, job_id: str, question: str) -> str:
        """Write a new pending clarification for ``job_id`` and wake any
        ``wait_for_clarification_request`` caller blocked on that job.
        Returns the new clarification id (``clr_<8 hex>``).
        """
        clr_id = f"clr_{secrets.token_hex(4)}"
        now = time.time()
        ev = threading.Event()
        with self._lock:
            self._conn.execute(
                "INSERT INTO job_clarifications "
                "(id, job_id, question, status, asked_at) VALUES (?, ?, ?, ?, ?)",
                (clr_id, job_id, question, STATUS_CLR_PENDING, now),
            )
            self._clarification_events[clr_id] = ev
            cond = self._job_clarification_conditions.get(job_id)
        # Notify outside the store lock — same pattern as _fire_completion.
        if cond is not None:
            with cond:
                cond.notify_all()
        return clr_id

    def answer_clarification(self, clr_id: str, answer: str) -> bool:
        """Record ``answer`` for a pending clarification and unblock its
        ``wait_for_clarification_answer`` caller.  Returns ``False`` if
        the clarification does not exist or is not pending.
        """
        now = time.time()
        with self._lock:
            cursor = self._conn.execute(
                "UPDATE job_clarifications "
                "SET answer = ?, status = ?, answered_at = ? "
                "WHERE id = ? AND status = ?",
                (answer, STATUS_CLR_ANSWERED, now, clr_id, STATUS_CLR_PENDING),
            )
            if cursor.rowcount == 0:
                return False
            ev = self._clarification_events.get(clr_id)
        if ev is not None:
            ev.set()
        return True

    def get_pending_clarifications(self, job_id: str) -> list[Clarification]:
        """Return all pending clarifications for ``job_id`` in ask order."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM job_clarifications "
                "WHERE job_id = ? AND status = ? ORDER BY asked_at",
                (job_id, STATUS_CLR_PENDING),
            ).fetchall()
        return [_row_to_clarification(r) for r in rows]

    def get_clarification(self, clr_id: str) -> Clarification | None:
        """Return the clarification by id, or ``None`` if not found."""
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM job_clarifications WHERE id = ?", (clr_id,),
            ).fetchone()
        return _row_to_clarification(row) if row is not None else None

    def wait_for_clarification_answer(
        self, clr_id: str, *, timeout_seconds: float,
    ) -> Clarification | None:
        """Block until the clarification is answered or ``timeout_seconds``
        elapses.  Returns the final ``Clarification`` (check ``status`` to
        distinguish ``answered`` from ``timed_out``).  Returns ``None`` if
        ``clr_id`` is unknown.
        """
        clr = self.get_clarification(clr_id)
        if clr is None:
            return None
        if clr.status != STATUS_CLR_PENDING:
            return clr
        with self._lock:
            ev = self._clarification_events.get(clr_id)
            if ev is None:
                ev = threading.Event()
                self._clarification_events[clr_id] = ev
        # Second check — answer_clarification may have fired in the race window.
        clr = self.get_clarification(clr_id)
        if clr is not None and clr.status != STATUS_CLR_PENDING:
            return clr
        ev.wait(timeout=timeout_seconds)
        return self.get_clarification(clr_id)

    def wait_for_clarification_request(
        self, job_id: str, *, timeout_seconds: float,
    ) -> list[Clarification]:
        """Block until at least one pending clarification arrives for
        ``job_id``, or the job completes (via ``_fire_completion``), or
        ``timeout_seconds`` elapses.  Returns the list of pending
        clarifications (empty on timeout or job completion with no questions).
        """
        cond = self._get_or_create_job_clarification_condition(job_id)
        with cond:
            # Check inside the condition lock to close the race where
            # add_clarification fires between our check and cond.wait().
            pending = self.get_pending_clarifications(job_id)
            if pending:
                return pending
            cond.wait(timeout=timeout_seconds)
        return self.get_pending_clarifications(job_id)

    def list_recent(
        self,
        *,
        project: str | None = None,
        status: str | None = None,
        limit: int = 50,
    ) -> list[Job]:
        clauses: list[str] = []
        params: list[Any] = []
        if project:
            clauses.append("project = ?")
            params.append(project)
        if status:
            clauses.append("status = ?")
            params.append(status)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(limit)
        with self._lock:
            rows = self._conn.execute(
                f"SELECT * FROM delegated_jobs {where} "
                "ORDER BY queued_at DESC LIMIT ?",
                params,
            ).fetchall()
        return [_row_to_job(r) for r in rows]

    def list_pending_for_inbox(
        self, inbox_id: str, *, limit: int = 50,
    ) -> list[Job]:
        """Completed or failed jobs in this inbox that have not yet
        been ``mark_read``."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM delegated_jobs "
                "WHERE inbox_id = ? "
                "  AND status IN (?, ?) "
                "  AND read_at IS NULL "
                "ORDER BY completed_at ASC LIMIT ?",
                (inbox_id, STATUS_COMPLETED, STATUS_FAILED, limit),
            ).fetchall()
        return [_row_to_job(r) for r in rows]

    def mark_read(self, job_ids: list[str]) -> int:
        if not job_ids:
            return 0
        now = time.time()
        placeholders = ",".join("?" for _ in job_ids)
        with self._lock:
            cur = self._conn.execute(
                f"UPDATE delegated_jobs SET read_at = ? "
                f"WHERE id IN ({placeholders}) AND read_at IS NULL",
                [now, *job_ids],
            )
            return cur.rowcount

    def prune_old(self, *, retain: int) -> int:
        """v23.0.0a2: keep only the most-recent ``retain`` rows by
        ``queued_at``. Older rows are deleted. Returns the deleted
        row count.

        Called from subsystem boot so unbounded growth doesn't
        accumulate across process lifetimes. Mirrors
        ``history.retain_recent_k`` semantics — newest wins.

        Safe to call concurrently with worker activity: the DELETE
        excludes the top-N most-recent rows, which always includes
        any in-flight ``queued`` / ``running`` jobs (their
        ``queued_at`` is current time-ish; pruning targets old
        ``completed`` / ``failed`` rows).
        """
        if retain < 1:
            return 0
        with self._lock:
            cur = self._conn.execute(
                "DELETE FROM delegated_jobs "
                "WHERE id NOT IN ("
                "  SELECT id FROM delegated_jobs "
                "  ORDER BY queued_at DESC LIMIT ?"
                ")",
                (retain,),
            )
            return cur.rowcount

    def recover_orphaned(self) -> int:
        """Mark any ``running`` rows as ``failed`` with reason
        ``server_restart``. Called once per process at subsystem init.

        Returns the count of rows recovered.
        """
        now = time.time()
        with self._lock:
            cur = self._conn.execute(
                "UPDATE delegated_jobs "
                "SET status = ?, error = ?, completed_at = ?, "
                "    duration_ms = COALESCE(duration_ms, 0) "
                "WHERE status = ?",
                (STATUS_FAILED, "server_restart", now, STATUS_RUNNING),
            )
            return cur.rowcount

    def sweep_stale_awaiting_caller(
        self, *, max_age_seconds: int, exclude_ids: frozenset[str] | None = None,
    ) -> int:
        """v26.0.0 — sweep ``awaiting_caller`` rows older than
        ``max_age_seconds`` to ``failed`` with reason
        ``caller_never_recorded_result``.

        Uses ``UPDATE … RETURNING id`` so the rows we just transitioned
        are the exact rows we fire ``_fire_completion`` for — no second
        SELECT, no race with a concurrent ``record_delegation_result``
        that updates the same row between SELECT and fan-out.

        ``exclude_ids`` (v26.0.0) lets the caller protect specific rows
        from the sweep — used by ``record_delegation_result`` to ensure
        the row being recorded is not swept out from under itself.

        Called periodically from the JobSubsystem heartbeat. Returns the
        count of rows swept. A ``max_age_seconds`` of 0 disables the
        sweep (callers should not call into this with 0; the subsystem
        suppresses the call instead).
        """
        if max_age_seconds <= 0:
            return 0
        cutoff = time.time() - max_age_seconds
        now = time.time()
        excluded = exclude_ids or frozenset()
        with self._lock:
            if excluded:
                placeholders = ",".join("?" for _ in excluded)
                cur = self._conn.execute(
                    f"UPDATE delegated_jobs "
                    f"SET status = ?, error = ?, completed_at = ?, "
                    f"    duration_ms = COALESCE(duration_ms, 0) "
                    f"WHERE status = ? AND queued_at < ? "
                    f"  AND id NOT IN ({placeholders}) "
                    f"RETURNING id",
                    (
                        STATUS_FAILED, "caller_never_recorded_result", now,
                        STATUS_AWAITING_CALLER, cutoff,
                        *excluded,
                    ),
                )
            else:
                cur = self._conn.execute(
                    "UPDATE delegated_jobs "
                    "SET status = ?, error = ?, completed_at = ?, "
                    "    duration_ms = COALESCE(duration_ms, 0) "
                    "WHERE status = ? AND queued_at < ? "
                    "RETURNING id",
                    (
                        STATUS_FAILED, "caller_never_recorded_result", now,
                        STATUS_AWAITING_CALLER, cutoff,
                    ),
                )
            swept_ids = [row["id"] for row in cur.fetchall()]
        # Fire completion notifications outside the lock so subscribers
        # (SSE/bridge/inbox waiters) see uniform behaviour across reasons.
        for jid in swept_ids:
            self._fire_completion(jid)
        return len(swept_ids)

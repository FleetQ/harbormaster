"""SQLite schema for the async delegate JobStore (v22.0.0a2)."""
from __future__ import annotations

SCHEMA = """
CREATE TABLE IF NOT EXISTS delegated_jobs (
    id TEXT PRIMARY KEY,
    inbox_id TEXT NOT NULL DEFAULT 'default',
    project TEXT NOT NULL,
    host TEXT,
    task TEXT NOT NULL,
    deliverable TEXT NOT NULL,
    allow_writes INTEGER NOT NULL,
    model TEXT,
    status TEXT NOT NULL,
    output TEXT,
    error TEXT,
    cid TEXT,
    queued_at REAL NOT NULL,
    started_at REAL,
    completed_at REAL,
    duration_ms INTEGER,
    read_at REAL,
    max_turns INTEGER NOT NULL DEFAULT 10,
    auto_commit INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_delegated_jobs_status
    ON delegated_jobs(status);
CREATE INDEX IF NOT EXISTS idx_delegated_jobs_inbox
    ON delegated_jobs(inbox_id, read_at, completed_at);
CREATE INDEX IF NOT EXISTS idx_delegated_jobs_project
    ON delegated_jobs(project);
CREATE INDEX IF NOT EXISTS idx_delegated_jobs_queued_at
    ON delegated_jobs(queued_at);
"""

STATUS_QUEUED = "queued"
STATUS_RUNNING = "running"
STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"
# v26.0.0 — instruction-mode initial state. Caller (the MCP client)
# must invoke `record_delegation_result` to transition to a terminal
# state. Workers ignore this status — they only claim STATUS_QUEUED.
STATUS_AWAITING_CALLER = "awaiting_caller"

VALID_STATUSES = frozenset({
    STATUS_QUEUED, STATUS_RUNNING, STATUS_COMPLETED, STATUS_FAILED,
    STATUS_AWAITING_CALLER,
})

# Idempotent ``ALTER TABLE ADD COLUMN`` migrations applied on
# ``JobStore`` open, in addition to the ``CREATE TABLE IF NOT EXISTS``
# above. Each entry is ``(column_name, full_column_definition)``.
# Pattern carried over from v21.0.8's network_log.db: PRAGMA
# table_info + ALTER when missing.
CLARIFICATION_SCHEMA = """
CREATE TABLE IF NOT EXISTS job_clarifications (
    id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL,
    question TEXT NOT NULL,
    answer TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    asked_at REAL NOT NULL,
    answered_at REAL
);

CREATE INDEX IF NOT EXISTS idx_clarifications_job_pending
    ON job_clarifications(job_id, status);
"""

STATUS_CLR_PENDING = "pending"
STATUS_CLR_ANSWERED = "answered"
STATUS_CLR_TIMED_OUT = "timed_out"

MIGRATIONS: list[tuple[str, str]] = [
    # v22.0.1 — caller-supplied turn budget. Default 10 matches the
    # pre-v22.0.1 hardcoded value so existing rows keep the same
    # behaviour after upgrade.
    ("max_turns", "max_turns INTEGER NOT NULL DEFAULT 10"),
    # v24.0.0a2 — caller-authorised auto-commit. Default 0 (no commit)
    # matches the v22+ "operator reviews + commits" contract; flipping
    # to 1 instructs the subagent to git commit after edits.
    ("auto_commit", "auto_commit INTEGER NOT NULL DEFAULT 0"),
    # v26.0.0 — execution provenance. 'subprocess' (default) matches
    # pre-v26 rows whose work was run by a JobWorker spawning `claude -p`.
    # 'instruction' rows were enqueued in instruction mode and recorded
    # via `record_delegation_result` by the calling MCP client.
    ("execution_mode", "execution_mode TEXT NOT NULL DEFAULT 'subprocess'"),
    # v26.0.0 — tokens reported by the caller via record_delegation_result.
    # Nullable: only populated when caller passes the value.
    ("tokens_used", "tokens_used INTEGER"),
    # v26.0.0 — the full rendered prompt (grounded context + role
    # suffix) for instruction-mode rows. Stored so a caller that lost
    # the original delegate_task / ask_project response and recovers
    # the packet via get_delegated_task gets a faithful copy. NULL
    # for subprocess rows — the worker builds its prompt at run time
    # via build_grounded_prompt.
    ("rendered_prompt", "rendered_prompt TEXT"),
]

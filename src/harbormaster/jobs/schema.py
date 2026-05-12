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
    read_at REAL
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

VALID_STATUSES = frozenset({
    STATUS_QUEUED, STATUS_RUNNING, STATUS_COMPLETED, STATUS_FAILED,
})

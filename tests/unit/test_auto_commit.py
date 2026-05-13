"""Unit tests for v24.0.0a2 auto_commit parameter on delegate_task."""
from __future__ import annotations

from pathlib import Path

from harbormaster.config import HarbormasterConfig
from harbormaster.jobs.store import JobStore
from harbormaster.jobs.worker import build_async_delegate_prompt
from harbormaster.server import build_server


def _tools(mcp):
    return {t.name: t for t in mcp._tool_manager.list_tools()}


def test_sync_delegate_no_auto_commit_uses_writes_suffix(monkeypatch):
    """allow_writes=True + auto_commit=False (default) → operator-commits
    prompt suffix."""
    from harbormaster.tools import delegate as _delegate

    captured: dict[str, str] = {}

    def fake(*, prompt, **_):
        captured["prompt"] = prompt
        return "ok"

    monkeypatch.setattr(_delegate, "run_backend", fake)

    fn = _tools(build_server(HarbormasterConfig()))["delegate_task"].fn
    fn(name="x", task="t", deliverable="d", allow_writes=True)
    assert "Do NOT git commit" in captured["prompt"]
    assert "git commit the changes" not in captured["prompt"]


def test_sync_delegate_auto_commit_swaps_suffix(monkeypatch):
    """allow_writes=True + auto_commit=True → subagent-commits prompt."""
    from harbormaster.tools import delegate as _delegate

    captured: dict[str, str] = {}

    def fake(*, prompt, **_):
        captured["prompt"] = prompt
        return "ok"

    monkeypatch.setattr(_delegate, "run_backend", fake)

    fn = _tools(build_server(HarbormasterConfig()))["delegate_task"].fn
    fn(
        name="x", task="t", deliverable="d",
        allow_writes=True, auto_commit=True,
    )
    assert "git commit the changes" in captured["prompt"]
    assert "conventional-commit message" in captured["prompt"]
    assert "Do NOT push" in captured["prompt"]
    assert "Do NOT git commit" not in captured["prompt"]


def test_sync_delegate_auto_commit_without_allow_writes_stays_read_only(monkeypatch):
    """auto_commit=True alone (allow_writes=False) must NOT escalate
    privileges — read-only prompt wins."""
    from harbormaster.tools import delegate as _delegate

    captured: dict[str, str] = {}

    def fake(*, prompt, **_):
        captured["prompt"] = prompt
        return "ok"

    monkeypatch.setattr(_delegate, "run_backend", fake)

    fn = _tools(build_server(HarbormasterConfig()))["delegate_task"].fn
    fn(
        name="x", task="t", deliverable="d",
        allow_writes=False, auto_commit=True,
    )
    assert "Read-only mode" in captured["prompt"]
    assert "git commit" not in captured["prompt"]
    # Read-only suffix contains "Do NOT edit files." — check the
    # writes-mode "You may edit files" intro string is absent.
    assert "You may edit files" not in captured["prompt"]


def test_jobstore_persists_auto_commit_flag(tmp_path: Path):
    """v24.0.0a2: auto_commit round-trips through the schema."""
    store = JobStore(tmp_path / "jobs.db")
    job_no = store.enqueue(
        project="p", host=None, task="t", deliverable="d",
        allow_writes=True, model=None,
    )
    job_yes = store.enqueue(
        project="p", host=None, task="t", deliverable="d",
        allow_writes=True, model=None, auto_commit=True,
    )
    assert job_no.auto_commit is False
    assert job_yes.auto_commit is True
    # Round-trip via get():
    assert store.get(job_no.id).auto_commit is False  # type: ignore[union-attr]
    assert store.get(job_yes.id).auto_commit is True  # type: ignore[union-attr]


def test_worker_prompt_uses_auto_commit_from_job(tmp_path: Path):
    """JobWorker.build_async_delegate_prompt branches on job.auto_commit,
    not a hardcoded value."""
    store = JobStore(tmp_path / "jobs.db")
    config = HarbormasterConfig()

    job_default = store.enqueue(
        project="p", host=None, task="t", deliverable="d",
        allow_writes=True, model=None, auto_commit=False,
    )
    job_commit = store.enqueue(
        project="p", host=None, task="t", deliverable="d",
        allow_writes=True, model=None, auto_commit=True,
    )

    default_prompt = build_async_delegate_prompt(job_default, config)
    commit_prompt = build_async_delegate_prompt(job_commit, config)

    assert "Do NOT git commit" in default_prompt
    assert "git commit the changes" in commit_prompt
    assert "Do NOT push" in commit_prompt


def test_migration_adds_auto_commit_to_pre_v24_db(tmp_path: Path):
    """A pre-v24.0.0a2 JobStore lacks auto_commit. Idempotent migration
    adds the column on first open."""
    import sqlite3

    db = tmp_path / "legacy.db"
    conn = sqlite3.connect(str(db))
    conn.executescript(
        """
        CREATE TABLE delegated_jobs (
            id TEXT PRIMARY KEY,
            inbox_id TEXT NOT NULL DEFAULT 'default',
            project TEXT NOT NULL,
            host TEXT, task TEXT NOT NULL, deliverable TEXT NOT NULL,
            allow_writes INTEGER NOT NULL, model TEXT,
            status TEXT NOT NULL, output TEXT, error TEXT, cid TEXT,
            queued_at REAL NOT NULL, started_at REAL, completed_at REAL,
            duration_ms INTEGER, read_at REAL,
            max_turns INTEGER NOT NULL DEFAULT 10
        );
        INSERT INTO delegated_jobs (
          id, project, task, deliverable, allow_writes, status, queued_at
        ) VALUES ('d_legacy23', 'p', 't', 'd', 1, 'completed', 1.0);
        """
    )
    conn.close()

    # Open through JobStore — migration should ADD COLUMN.
    store = JobStore(db)
    job = store.get("d_legacy23")
    assert job is not None
    assert job.auto_commit is False  # default backfill

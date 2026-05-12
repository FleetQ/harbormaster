"""HTTP-endpoint tests for the v22.0.0a4 Delegated Jobs UI surface.

Exercises ``/api/delegated-jobs``, ``/api/delegated-jobs/summary``,
``/api/delegated-jobs/{job_id}`` and the ``/jobs`` HTML page. Uses the
fastapi TestClient directly — no subprocess spawn, no fake_claude.
The JobStore is seeded by hand so the tests stay deterministic.
"""
from __future__ import annotations

import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from harbormaster.config import HarbormasterConfig
from harbormaster.jobs.subsystem import get_subsystem, shutdown_subsystem
from harbormaster.ui import create_app


@pytest.fixture(autouse=True)
def _isolate_subsystem():
    yield
    shutdown_subsystem()


@pytest.fixture
def env(tmp_path: Path, monkeypatch):
    """Bundle a config + a TestClient sharing the same isolated
    HARBORMASTER_JOBS_DB so test seeds land in the same store the
    HTTP endpoints read from."""
    monkeypatch.setenv("HARBORMASTER_JOBS_DB", str(tmp_path / "jobs.db"))
    config = HarbormasterConfig()
    app = create_app(config)
    client = TestClient(app)

    class Env:
        pass

    e = Env()
    e.config = config
    e.client = client
    return e


def _seed_one_job(
    config: HarbormasterConfig,
    *,
    project: str = "alpha",
    status: str | None = None,
    output: str | None = None,
    error: str | None = None,
    inbox_id: str = "default",
    allow_writes: bool = False,
    completed_recently: bool = True,
) -> str:
    """Insert a job in a chosen final state. Returns the new job id."""
    sub = get_subsystem(config)
    job = sub.store.enqueue(
        project=project,
        host=None,
        task=f"t-for-{project}",
        deliverable="d",
        allow_writes=allow_writes,
        model=None,
        inbox_id=inbox_id,
    )
    if status is None or status == "queued":
        return job.id
    # Drive the row into the requested status directly. claim_next_queued
    # is FIFO across the whole store so it's a poor fit for per-row seeds.
    if status == "running":
        with sub.store._lock:
            sub.store._conn.execute(
                "UPDATE delegated_jobs SET status='running', started_at=? "
                "WHERE id=?",
                (time.time(), job.id),
            )
        return job.id
    if status == "completed":
        sub.store.complete(job.id, output=output or "done", duration_ms=10)
    elif status == "failed":
        sub.store.fail(
            job.id, error=error or "Error: ... [cid=abc12345] — code=oops: bad",
            cid="abc12345", duration_ms=10,
        )
    if not completed_recently:
        # Push completed_at back 25 hours so it's excluded from "today"
        # counters in summary.
        old = time.time() - 25 * 3600
        with sub.store._lock:
            sub.store._conn.execute(
                "UPDATE delegated_jobs SET completed_at=? WHERE id=?",
                (old, job.id),
            )
    return job.id


def test_jobs_page_renders(env):
    r = env.client.get("/jobs")
    assert r.status_code == 200
    body = r.text
    # Page title is set via the {% block page_title %} extension.
    assert "Delegated Jobs" in body
    # Filter chips wired through.
    assert "All" in body
    assert "data-empty-state=\"jobs.no-jobs\"" in body


def test_api_delegated_jobs_list_returns_seeded_rows(env):
    config = env.config
    _seed_one_job(config, project="alpha", status="completed")
    _seed_one_job(config, project="beta", status="failed")

    r = env.client.get("/api/delegated-jobs")
    assert r.status_code == 200
    data = r.json()
    assert data["count"] == 2
    statuses = {j["status"] for j in data["jobs"]}
    assert statuses == {"completed", "failed"}


def test_api_delegated_jobs_filters_by_status(env):
    config = env.config
    _seed_one_job(config, project="alpha", status="completed")
    _seed_one_job(config, project="beta", status="failed")
    _seed_one_job(config, project="gamma", status="completed")

    r = env.client.get("/api/delegated-jobs?status=completed")
    assert r.status_code == 200
    data = r.json()
    assert data["count"] == 2
    assert all(j["status"] == "completed" for j in data["jobs"])
    assert data["filters"] == {"status": "completed", "project": None}


def test_api_delegated_jobs_filters_by_project(env):
    config = env.config
    _seed_one_job(config, project="alpha", status="completed")
    _seed_one_job(config, project="beta", status="completed")

    r = env.client.get("/api/delegated-jobs?project=alpha")
    assert r.status_code == 200
    data = r.json()
    assert data["count"] == 1
    assert data["jobs"][0]["project"] == "alpha"


def test_api_delegated_jobs_rejects_bad_status(env):
    r = env.client.get("/api/delegated-jobs?status=bogus")
    assert r.status_code == 400


def test_api_delegated_jobs_rejects_bad_limit(env):
    r = env.client.get("/api/delegated-jobs?limit=0")
    assert r.status_code == 400
    r2 = env.client.get("/api/delegated-jobs?limit=999999")
    assert r2.status_code == 400


def test_api_delegated_jobs_summary_counts(env):
    config = env.config
    _seed_one_job(config, project="a", status="queued")
    _seed_one_job(config, project="b", status="running")
    _seed_one_job(config, project="c", status="completed")
    _seed_one_job(config, project="d", status="failed")
    # An older completion that should NOT count toward _today.
    _seed_one_job(
        config, project="e", status="completed", completed_recently=False,
    )

    r = env.client.get("/api/delegated-jobs/summary")
    assert r.status_code == 200
    data = r.json()
    assert data == {
        "queued": 1, "running": 1,
        "completed_today": 1, "failed_today": 1,
    }


def test_api_delegated_job_full_returns_row(env):
    config = env.config
    job_id = _seed_one_job(
        config, project="alpha", status="completed",
        output="full markdown output",
    )

    r = env.client.get(f"/api/delegated-jobs/{job_id}")
    assert r.status_code == 200
    data = r.json()
    assert data["job_id"] == job_id
    assert data["status"] == "completed"
    assert data["output"] == "full markdown output"


def test_api_delegated_job_full_returns_404(env):
    r = env.client.get("/api/delegated-jobs/d_nope")
    assert r.status_code == 404

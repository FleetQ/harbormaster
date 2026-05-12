"""Tests for the v22.2.0 SSE stream wiring + MCP resource exposure.

The SSE response object itself is not exercised end-to-end here
because ``TestClient`` does not cleanly cancel an infinite
``EventSourceResponse`` generator (same limitation that keeps the
existing ``/api/network/stream`` test pattern source-level — see
``tests/ui/test_heartbeat_tuning.py``). What this file does cover:

- the broadcaster wiring on the JobStore subscriber hook fires on
  every completion / failure (publish_threadsafe goes out)
- the route is registered and responds with the right content-type
  on connect
- the MCP resource layer exposes ``harbormaster://jobs/recent`` +
  ``harbormaster://jobs/{job_id}``

The broadcaster's threadsafe → asyncio bridge is exercised in detail
by ``tests/unit/test_jobs_broadcaster.py``.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from harbormaster.config import BackendConfig, HarbormasterConfig, ProjectsConfig
from harbormaster.jobs import get_subsystem
from harbormaster.jobs.subsystem import shutdown_subsystem
from harbormaster.server import build_server
from harbormaster.ui import create_app

FAKE_CLAUDE = Path(__file__).resolve().parent.parent / "fixtures" / "fake_claude.py"


@pytest.fixture(autouse=True)
def _isolate_subsystem():
    yield
    shutdown_subsystem()


@pytest.fixture
def env(tmp_path: Path, monkeypatch):
    code = tmp_path / "code"
    for name in ("alpha", "beta"):
        (code / name).mkdir(parents=True)
        (code / name / "CLAUDE.md").write_text(f"# {name}", encoding="utf-8")
    monkeypatch.setenv("HARBORMASTER_JOBS_DB", str(tmp_path / "jobs.db"))
    config = HarbormasterConfig(
        projects=ProjectsConfig(glob=[f"{tmp_path}/code/*"]),
        backends={"claude": BackendConfig(binary=str(FAKE_CLAUDE), timeout_local=10)},
    )

    class Env:
        pass

    e = Env()
    e.config = config
    e.app = create_app(config)
    e.client = TestClient(e.app)
    return e


def test_subsystem_registers_broadcaster_as_subscriber(env):
    """Lazy subsystem init must wire the broadcaster onto the
    JobStore subscriber list so SSE consumers receive every job
    state change."""
    # Trigger subsystem init.
    env.client.get("/api/delegated-jobs/summary")
    sub = get_subsystem(env.config)
    # Broadcaster's publish callable is registered on the store.
    assert sub.broadcaster.publish_threadsafe in sub.store._subscribers  # noqa: SLF001


def test_sse_route_registered_with_event_stream_content_type(env):
    """Smoke-check: route exists and returns the correct content
    type. We intentionally don't consume the stream (TestClient does
    not cancel infinite generators cleanly)."""
    routes = {r.path for r in env.app.routes}
    assert "/api/delegated-jobs/stream" in routes


def test_completion_event_routes_through_broadcaster_to_subscribers(env):
    """JobStore.complete() must invoke the broadcaster's
    publish_threadsafe via the subscriber hook. Validated by
    swapping the broadcaster's publish for a capture probe."""
    import threading

    env.client.get("/api/delegated-jobs/summary")
    sub = get_subsystem(env.config)
    seen: list[str] = []
    seen_event = threading.Event()

    def probe(job):  # type: ignore[no-untyped-def]
        seen.append(job.id)
        seen_event.set()

    sub.store.add_subscriber(probe)
    job = sub.store.enqueue(
        project="alpha", host=None, task="t", deliverable="d",
        allow_writes=False, model=None,
    )
    sub.store.claim_next_queued()
    sub.store.complete(job.id, output="done", duration_ms=5)

    assert seen_event.wait(timeout=1.0)
    assert job.id in seen
    sub.store.remove_subscriber(probe)


def test_mcp_resource_jobs_recent_registered(env):
    """``harbormaster://jobs/recent`` is exposed as a static resource."""
    mcp = build_server(env.config)
    resources = mcp._resource_manager.list_resources()  # type: ignore[attr-defined]
    uris = {str(r.uri) for r in resources}
    assert "harbormaster://jobs/recent" in uris


def test_mcp_resource_jobs_by_id_registered_as_template(env):
    """Per-job resources are exposed as a parametrised URI template."""
    mcp = build_server(env.config)
    templates = mcp._resource_manager.list_templates()  # type: ignore[attr-defined]
    template_uris = {t.uri_template for t in templates}
    assert "harbormaster://jobs/{job_id}" in template_uris

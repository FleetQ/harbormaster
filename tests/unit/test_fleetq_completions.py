"""Unit tests for v24.0.0a7 CompletionPublisher.

The HTTP POST is stubbed via monkeypatch; subprocess + network are
not exercised. End-to-end against a live FleetQ relay is operator-
verified out-of-band.
"""
from __future__ import annotations

import time

from harbormaster.config import FleetQConfig, HarbormasterConfig
from harbormaster.fleetq.completions import (
    CompletionPublisher,
    _build_payload,
)
from harbormaster.jobs.store import Job

_DUMMY_JOB = Job(
    id="d_test01", inbox_id="default", project="alpha", host=None,
    task="audit the auth module" * 50,  # > 2000 chars to test trim
    deliverable="markdown report", allow_writes=True, model=None,
    status="completed", output="ok" * 3000,  # > 4000 chars
    error=None, cid="ff00", queued_at=1.0, started_at=2.0,
    completed_at=3.0, duration_ms=1000, read_at=None, max_turns=10,
    auto_commit=False,
)


def test_publisher_disarmed_when_publish_completions_false():
    cfg = HarbormasterConfig(
        fleetq=FleetQConfig(
            enabled=True, publish_completions=False, team_id="t1",
        ),
    )
    pub = CompletionPublisher(cfg)
    assert pub.is_armed() is False


def test_publisher_disarmed_when_team_id_missing():
    cfg = HarbormasterConfig(
        fleetq=FleetQConfig(
            enabled=True, publish_completions=True, team_id="",
        ),
    )
    pub = CompletionPublisher(cfg)
    assert pub.is_armed() is False


def test_publisher_disarmed_when_token_missing(monkeypatch):
    monkeypatch.delenv("FLEETQ_API_TOKEN", raising=False)
    cfg = HarbormasterConfig(
        fleetq=FleetQConfig(
            enabled=True, publish_completions=True, team_id="t1",
        ),
    )
    pub = CompletionPublisher(cfg)
    assert pub.is_armed() is False


def test_publisher_armed_when_all_three_gates_pass(monkeypatch):
    monkeypatch.setenv("FLEETQ_API_TOKEN", "secret")
    cfg = HarbormasterConfig(
        fleetq=FleetQConfig(
            enabled=True, publish_completions=True, team_id="t1",
        ),
    )
    pub = CompletionPublisher(cfg)
    assert pub.is_armed() is True


def test_publish_no_op_when_disarmed(monkeypatch):
    cfg = HarbormasterConfig()  # bare defaults — disarmed
    pub = CompletionPublisher(cfg)
    captured = []
    monkeypatch.setattr(pub, "_post", lambda payload: captured.append(payload))
    pub.publish(_DUMMY_JOB)
    # No background thread should fire when disarmed.
    time.sleep(0.05)
    assert captured == []


def test_publish_only_fires_on_terminal_status(monkeypatch):
    monkeypatch.setenv("FLEETQ_API_TOKEN", "secret")
    cfg = HarbormasterConfig(
        fleetq=FleetQConfig(
            enabled=True, publish_completions=True, team_id="t1",
        ),
    )
    pub = CompletionPublisher(cfg)
    captured: list[dict] = []

    def fake_post(payload):
        captured.append(payload)

    monkeypatch.setattr(pub, "_post", fake_post)

    # running / queued statuses must not fire
    for status in ("running", "queued"):
        from dataclasses import replace
        non_terminal = replace(_DUMMY_JOB, status=status)
        pub.publish(non_terminal)
    time.sleep(0.05)
    assert captured == []

    # completed fires
    pub.publish(_DUMMY_JOB)
    # Wait for daemon thread
    for _ in range(50):
        if captured:
            break
        time.sleep(0.02)
    assert len(captured) == 1
    assert captured[0]["job_id"] == "d_test01"
    assert captured[0]["status"] == "completed"


def test_payload_trims_long_strings():
    """v24.0.0a7: task capped at 2000, deliverable at 1000, output/error
    at 4000 — matches the fleetq-bridge contract."""
    payload = _build_payload(_DUMMY_JOB, "team-uuid")
    assert len(payload["task"]) <= 2000
    assert len(payload["deliverable"]) <= 1000
    assert payload["output"] is not None and len(payload["output"]) <= 4000
    assert payload["team_id"] == "team-uuid"
    assert payload["cid"] == "ff00"


def test_payload_shape_matches_fleetq_contract():
    """Schema fields per the fleetq-bridge delivery report."""
    payload = _build_payload(_DUMMY_JOB, "team-uuid")
    expected_keys = {
        "job_id", "team_id", "project", "host", "task",
        "deliverable", "allow_writes", "status", "output", "error",
        "cid", "queued_at", "completed_at", "duration_ms", "model",
        "max_turns", "inbox_id",
    }
    assert set(payload.keys()) == expected_keys


def test_payload_handles_none_output_and_error():
    from dataclasses import replace
    job = replace(_DUMMY_JOB, output=None, error=None)
    payload = _build_payload(job, "team-uuid")
    assert payload["output"] is None
    assert payload["error"] is None


def test_post_handles_http_error_gracefully(monkeypatch):
    """Network errors are logged + swallowed so they don't kill the
    JobStore worker."""
    monkeypatch.setenv("FLEETQ_API_TOKEN", "secret")
    cfg = HarbormasterConfig(
        fleetq=FleetQConfig(
            enabled=True, publish_completions=True, team_id="t1",
        ),
    )
    pub = CompletionPublisher(cfg)

    # Force the POST to fail with a connection error.
    def raising_urlopen(*_, **__):
        raise ConnectionRefusedError("relay unreachable")

    monkeypatch.setattr(
        "harbormaster.fleetq.completions.urllib.request.urlopen",
        raising_urlopen,
    )
    # Must NOT raise.
    pub._post(_build_payload(_DUMMY_JOB, "t1"))


def test_subsystem_wires_publisher_when_armed(monkeypatch, tmp_path):
    """The JobStore subsystem registers the publisher as a subscriber
    when the three-gate check passes at boot."""
    monkeypatch.setenv("HARBORMASTER_JOBS_DB", str(tmp_path / "jobs.db"))
    monkeypatch.setenv("FLEETQ_API_TOKEN", "secret")
    cfg = HarbormasterConfig(
        fleetq=FleetQConfig(
            enabled=True, publish_completions=True, team_id="t1",
        ),
    )

    from harbormaster.jobs.subsystem import (
        get_subsystem,
        shutdown_subsystem,
    )
    sub = get_subsystem(cfg)
    try:
        # Two subscribers: broadcaster + completion publisher.
        callables = [s.__qualname__ for s in sub.store._subscribers]
        assert any("publish" in c for c in callables), (
            f"expected publisher in subscribers; got {callables}"
        )
    finally:
        shutdown_subsystem()


def test_subsystem_skips_publisher_when_disarmed(monkeypatch, tmp_path):
    """Bare defaults — no FleetQ → only the broadcaster subscriber."""
    monkeypatch.setenv("HARBORMASTER_JOBS_DB", str(tmp_path / "jobs.db"))
    monkeypatch.delenv("FLEETQ_API_TOKEN", raising=False)

    from harbormaster.jobs.subsystem import (
        get_subsystem,
        shutdown_subsystem,
    )
    sub = get_subsystem(HarbormasterConfig())
    try:
        assert len(sub.store._subscribers) == 1  # just the broadcaster
    finally:
        shutdown_subsystem()

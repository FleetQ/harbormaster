"""v27.1.3 — [delegate] subprocess_timeout wiring.

Proves that a local async delegate job honours a configured
``subprocess_timeout`` > 600s, and that the value actually reaches the
subprocess executor (``subprocess.run(timeout=...)``) — asserted by
capturing the timeout, never by sleeping wall-clock.
"""
from __future__ import annotations

import time
from pathlib import Path

import pytest

from harbormaster.backends.claude import ClaudeBackend
from harbormaster.backends.base import BackendError
from harbormaster.config import (
    BackendConfig,
    DelegateConfig,
    HarbormasterConfig,
)
from harbormaster.jobs.store import JobStore
from harbormaster.jobs.schema import STATUS_COMPLETED
from harbormaster.jobs.worker import JobWorker, _apply_subprocess_timeout


def _wait_until(predicate, timeout: float = 2.0, poll: float = 0.02):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate():
            return True
        time.sleep(poll)
    return False


def test_apply_subprocess_timeout_overrides_backend_timeout_local():
    """When the knob is set, every backend's timeout_local is replaced
    by subprocess_timeout (default timeout_remote is left alone)."""
    cfg = HarbormasterConfig(delegate=DelegateConfig(subprocess_timeout=5400))
    out = _apply_subprocess_timeout(cfg)
    assert out.backends["claude"].timeout_local == 5400
    # remote timeout untouched — SSH async jobs use hosts.total_timeout.
    assert out.backends["claude"].timeout_remote == 600


def test_apply_subprocess_timeout_noop_when_unset():
    """Unset (None) → config returned untouched, so async jobs inherit
    the backend's timeout_local (backward compatible)."""
    cfg = HarbormasterConfig()  # delegate.subprocess_timeout defaults to None
    out = _apply_subprocess_timeout(cfg)
    assert out is cfg
    assert out.backends["claude"].timeout_local == 300


def test_worker_hands_executor_config_with_overridden_timeout(
    tmp_path: Path, monkeypatch,
):
    """End-to-end through the JobWorker: a local async job's executor
    (run_backend) receives a config whose timeout_local == 5400 (> 600),
    NOT the default 300."""
    from harbormaster.jobs import worker as _worker

    captured: dict[str, object] = {}

    def fake_run(*, config, **_kw):
        captured["timeout_local"] = config.backends["claude"].timeout_local
        return "ok"

    monkeypatch.setattr(_worker, "run_backend", fake_run)
    monkeypatch.setattr(_worker, "build_grounded_prompt", lambda **k: "x")

    store = JobStore(tmp_path / "jobs.db")
    job = store.enqueue(
        project="alpha", host=None, task="t", deliverable="d",
        allow_writes=False, model=None,
    )
    cfg = HarbormasterConfig(delegate=DelegateConfig(subprocess_timeout=5400))
    w = JobWorker(config=cfg, store=store, poll_interval_s=0.01)
    w.start()
    try:
        assert _wait_until(
            lambda: (g := store.get(job.id)) is not None
            and g.status == STATUS_COMPLETED,
        )
    finally:
        w.stop(timeout=1.0)

    assert captured["timeout_local"] == 5400


def test_ask_local_passes_configured_timeout_to_subprocess(monkeypatch, tmp_path):
    """Closes the loop: the backend feeds cfg.timeout_local straight into
    subprocess.run(timeout=...). Mock the subprocess so no real 5400s
    sleep happens — assert the timeout kwarg only."""
    captured: dict[str, object] = {}

    class _FakeProc:
        returncode = 0
        stdout = '{"result": "done"}'
        stderr = ""

    def fake_subprocess_run(cmd, **kwargs):
        captured["timeout"] = kwargs.get("timeout")
        return _FakeProc()

    monkeypatch.setattr(
        "harbormaster.backends.claude.subprocess.run", fake_subprocess_run,
    )

    backend = ClaudeBackend(BackendConfig(timeout_local=5400))
    result = backend.ask_local(
        cwd=tmp_path, prompt="hi", max_turns=10, model=None,
    )
    assert result.output == "done"
    assert captured["timeout"] == 5400

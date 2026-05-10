"""v9.0.0a2: tests for the new `--url` flag on `dispatcher status`.

When `--url` is provided the CLI fetches GET <url>/api/dispatcher/status
and merges the runtime block into the JSON output. Failures are
non-fatal — the CLI prints a warning and returns the config-only
payload.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from pytest_httpserver import HTTPServer

from harbormaster.dispatcher_cli import main


@pytest.fixture
def empty_config(tmp_path: Path) -> Path:
    cfg = tmp_path / "harbormaster.toml"
    cfg.write_text("[server]\n")
    return cfg


def test_url_fetches_and_merges_runtime_payload(
    empty_config: Path,
    httpserver: HTTPServer,
    capsys: pytest.CaptureFixture[str],
) -> None:
    runtime: dict[str, Any] = {
        "running": [
            {"tool": "ask_project", "project": "harbormaster", "started_at": 1700000000.0},
        ],
        "active_workers": 1,
        "queue_depth": 0,
        "last_dispatched_at": 1700000000.5,
        "tools": {"ask_project": {"in_flight": 1, "total_completed": 5, "total_failed": 0}},
    }
    httpserver.expect_request("/api/dispatcher/status").respond_with_json(runtime)

    rc = main(
        [
            "status",
            "--config", str(empty_config),
            "--url", httpserver.url_for(""),
            "--json",
        ]
    )
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert "runtime" in payload
    assert payload["runtime"] == runtime


def test_url_fetch_failure_falls_back_with_warning(
    empty_config: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    rc = main(
        [
            "status",
            "--config", str(empty_config),
            # Unreachable URL — request fails with URLError.
            "--url", "http://127.0.0.1:1",
            "--json",
        ]
    )
    assert rc == 0
    captured = capsys.readouterr()
    assert "Warning" in captured.err
    payload = json.loads(captured.out)
    # Config-only fields still present; runtime omitted.
    assert "dispatcher_max_workers" in payload
    assert "runtime" not in payload


def test_url_text_format_includes_runtime_block(
    empty_config: Path,
    httpserver: HTTPServer,
    capsys: pytest.CaptureFixture[str],
) -> None:
    httpserver.expect_request("/api/dispatcher/status").respond_with_json({
        "running": [],
        "active_workers": 0,
        "queue_depth": 0,
        "last_dispatched_at": None,
        "tools": {"ask_project": {"in_flight": 0, "total_completed": 3, "total_failed": 1}},
    })
    rc = main(
        ["status", "--config", str(empty_config), "--url", httpserver.url_for("")]
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "Live runtime (v9.0.0a2)" in out
    assert "ask_project: in_flight=0 completed=3 failed=1" in out

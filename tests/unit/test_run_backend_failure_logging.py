"""v21.0.7: when a backend call fails, the agent / operator must get
actionable debug information instead of the bare ``"Error: ..."``
string that v21.0.6 and earlier returned.

These tests pin three guarantees of the v21.0.7 patch:

1. ``run_backend`` enriches the agent-facing error string with a
   short correlation id, elapsed time, error code, and project/host
   identifiers — so the agent can tell which call failed.

2. ``run_backend`` emits a structured WARNING log line carrying the
   same correlation id, so an operator can grep
   ``~/.harbormaster/`` / journald for the matching context.

3. ``run_backend`` mirrors the failure into the UI ``network_log``
   (``mcp_calls`` table) with ``status='error'``, so the dashboard
   Activity / Timeline tabs surface failed dispatches — not only
   successful ones. Mirrors the v21.0.6 unified-activity pattern.

Best-effort: a crash inside the instrumentation must never break the
error path that's already in flight back to the agent.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

import pytest

from harbormaster.backends.base import BackendError, BackendResult
from harbormaster.config import BackendConfig, HarbormasterConfig
from harbormaster.tools import _helpers as helpers
from harbormaster.ui.network_log import network_log

CID_RE = re.compile(r"\[cid=([0-9a-f]{8})\]")


class _FailingBackend:
    """Mock backend whose ask_local / ask_remote always raise a given
    BackendError. Mirrors the shape used by tests/ui/test_v21_model_selection.py."""

    name = "claude"

    def __init__(self, error: BackendError) -> None:
        self.cfg = BackendConfig(output_word_cap=800)
        self._error = error

    def ask_local(self, *, cwd: Path, prompt: str, max_turns: int, model: object = None) -> BackendResult:
        raise self._error

    def ask_remote(self, **kwargs: object) -> BackendResult:
        raise self._error


def _install_backend(monkeypatch: pytest.MonkeyPatch, backend: object, tmp_path: Path) -> None:
    monkeypatch.setattr(helpers, "get_backend_for_project", lambda *a, **k: backend)
    monkeypatch.setattr(helpers, "resolve_project", lambda *a, **k: tmp_path)
    monkeypatch.setattr(helpers, "validate_project_name", lambda *a, **k: None)


def _network_log_rows() -> list[dict[str, object]]:
    cur = network_log._conn.execute(  # noqa: SLF001 — internal API
        "SELECT target, tool, status, question_preview, duration_ms "
        "FROM mcp_calls ORDER BY id",
    )
    return [
        {
            "target": r[0],
            "tool": r[1],
            "status": r[2],
            "question_preview": r[3],
            "duration_ms": r[4],
        }
        for r in cur.fetchall()
    ]


def test_run_backend_failure_returns_enriched_error_string(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Agent-facing string must include a correlation id, the tool +
    project + host, an elapsed_ms, the error code, and the original
    message — without losing the ``Error: ...`` prefix that callers
    historically pattern-match on."""
    _install_backend(
        monkeypatch,
        _FailingBackend(BackendError("timeout: claude -p exceeded 60s (elapsed=60.0s)", code="timeout")),
        tmp_path,
    )

    out = helpers.run_backend(
        name="harbormaster",
        prompt="why are we here?",
        max_turns=2,
        host=None,
        config=HarbormasterConfig(),
        label_prefix="ask",
    )

    # Backwards-compat: the literal "Error:" prefix is load-bearing —
    # fan_out.py filters target answers on it, and external agents
    # pattern-match on it too.
    assert out.startswith("Error: "), out
    m = CID_RE.search(out)
    assert m is not None, f"missing correlation id in {out!r}"
    assert "ask(name='harbormaster', host='local')" in out
    assert "failed after" in out and " ms " in out
    assert "code=timeout" in out
    assert "exceeded 60s" in out


def test_run_backend_failure_records_in_network_log(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Dashboard Activity tab must see the failure: one mcp_calls row
    with status='error', the correct target/tool, and a non-None
    duration_ms."""
    _install_backend(
        monkeypatch,
        _FailingBackend(BackendError("ssh to 'box' failed (rc=255)", code="ssh_error")),
        tmp_path,
    )

    helpers.run_backend(
        name="harbormaster",
        prompt="hello",
        max_turns=2,
        host=None,
        config=HarbormasterConfig(),
        label_prefix="ask",
    )

    rows = _network_log_rows()
    assert len(rows) == 1, rows
    row = rows[0]
    assert row["target"] == "harbormaster"
    assert row["tool"] == "ask"
    assert row["status"] == "error"
    assert row["question_preview"] == "hello"
    assert isinstance(row["duration_ms"], int)


def test_run_backend_failure_emits_structured_warning_log(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    """One WARNING line with cid, code, project, host. Operator must
    be able to grep ``cid=<id>`` and find the failure context."""
    _install_backend(
        monkeypatch,
        _FailingBackend(BackendError("kaboom", code="exit_nonzero")),
        tmp_path,
    )

    with caplog.at_level(logging.WARNING, logger="harbormaster.tools._helpers"):
        out = helpers.run_backend(
            name="alpha",
            prompt="hi",
            max_turns=2,
            host=None,
            config=HarbormasterConfig(),
            label_prefix="delegate",
        )

    m = CID_RE.search(out)
    assert m is not None
    cid = m.group(1)

    matching = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert matching, "no WARNING log emitted"
    msg = matching[-1].getMessage()
    assert f"cid={cid}" in msg
    assert "code=exit_nonzero" in msg
    assert "project=alpha" in msg
    assert "host=local" in msg
    assert "tool=delegate" in msg


def test_run_backend_failure_logs_remote_host(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    """When host!=None, the warning + agent-facing string must reflect
    the actual host so the operator can disambiguate
    'remote box stuck' from 'local subprocess stuck'."""
    backend = _FailingBackend(
        BackendError(
            "SSH to 'webserver' exceeded 120s (elapsed=120.1s, connect_timeout=10s, total_timeout=120s)",
            code="timeout",
        ),
    )
    _install_backend(monkeypatch, backend, tmp_path)
    cfg = HarbormasterConfig()

    with caplog.at_level(logging.WARNING, logger="harbormaster.tools._helpers"):
        out = helpers.run_backend(
            name="harbormaster",
            prompt="ping",
            max_turns=1,
            host="webserver",
            config=cfg,
            label_prefix="ask",
        )

    assert "host='webserver'" in out
    assert "connect_timeout=10s" in out
    msgs = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert any("host=webserver" in m for m in msgs), msgs


def test_run_backend_failure_swallows_instrumentation_crash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If network_log.record() blows up, run_backend must STILL return
    the enriched error string. Instrumentation is best-effort —
    breakage inside it cannot mask the original failure."""
    _install_backend(
        monkeypatch,
        _FailingBackend(BackendError("kaboom", code="timeout")),
        tmp_path,
    )

    def _boom(**kwargs: object) -> None:
        raise RuntimeError("network_log explosion")

    monkeypatch.setattr(network_log, "record", _boom)

    # Must not raise — must still return the enriched string with cid.
    out = helpers.run_backend(
        name="harbormaster",
        prompt="hi",
        max_turns=1,
        host=None,
        config=HarbormasterConfig(),
        label_prefix="ask",
    )
    assert out.startswith("Error: ")
    assert "[cid=" in out
    assert "code=timeout" in out


def test_correlation_id_format() -> None:
    """8 hex chars. Predictable shape for grep / dashboard linking."""
    cid = helpers._new_correlation_id()
    assert re.fullmatch(r"[0-9a-f]{8}", cid), cid


def test_correlation_ids_are_unique_per_call() -> None:
    """Two consecutive failures get distinct ids."""
    ids = {helpers._new_correlation_id() for _ in range(100)}
    assert len(ids) == 100

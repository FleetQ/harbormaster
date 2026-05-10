"""Shared pytest setup. Inserts src/ on sys.path so imports work without install."""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

# v11.0.0a1: redirect the persistent network log to a tmp file BEFORE any
# test imports `harbormaster.ui.network_log`. The module-level singleton
# is constructed at import time; setting the env var afterwards would
# leak writes into `~/.harbormaster/network_log.db`. Done at module top
# (not in a fixture) precisely because fixtures run too late.
_NETWORK_LOG_TMPDIR = tempfile.mkdtemp(prefix="hm-tests-network-log-")
os.environ["HARBORMASTER_NETWORK_LOG_DB"] = str(
    Path(_NETWORK_LOG_TMPDIR) / "network_log.db"
)

# v11.0.0a2: same isolation for the memory-revisions DB.
_MEMORY_REVISIONS_TMPDIR = tempfile.mkdtemp(prefix="hm-tests-memory-revisions-")
os.environ["HARBORMASTER_MEMORY_REVISIONS_DB"] = str(
    Path(_MEMORY_REVISIONS_TMPDIR) / "memory_revisions.db"
)


# v16.0.0a1: autouse fixture promoting the ad-hoc reset pattern from
# tests/ui/test_network_event_filtering.py up to session-wide. The
# singleton ``network_log`` shares its ``mcp_calls`` table across tests
# unless explicitly truncated; before v16 this footgun was rediscovered
# every time a new test surface touched the network log (latest case
# in v15.0.0a4 N-way reembed call counters). Truncating at function
# scope keeps per-test counts deterministic without forcing every test
# file to wire up its own reset.
from collections.abc import Iterator  # noqa: E402

import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _reset_network_log() -> Iterator[None]:
    """Truncate the ``network_log`` singleton's ``mcp_calls`` table
    around every test. Lazy import so the optional UI extra isn't
    required for non-UI test runs.
    """
    try:
        from harbormaster.ui import network_log as _nl
    except Exception:
        yield
        return
    with _nl.network_log._lock:  # type: ignore[attr-defined]
        _nl.network_log._conn.execute("DELETE FROM mcp_calls")  # type: ignore[attr-defined]
        _nl.network_log._conn.commit()  # type: ignore[attr-defined]
    yield
    with _nl.network_log._lock:  # type: ignore[attr-defined]
        _nl.network_log._conn.execute("DELETE FROM mcp_calls")  # type: ignore[attr-defined]
        _nl.network_log._conn.commit()  # type: ignore[attr-defined]

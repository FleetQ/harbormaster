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

"""FleetQ Bridge live runtime state — cross-process JSON file.

v3.0.0a2: the harbormaster-mcp process owns the live bridge connection
(register, heartbeat, relay subscribe). The harbormaster-ui process is
a separate Python process that needs to surface that state. Solution:
the MCP process atomically writes a small JSON file, and the UI process
reads it on demand.

File location:
    $HARBORMASTER_BRIDGE_STATE_FILE  (override; tests + custom homedirs)
    or  ~/.harbormaster/bridge-state.json  (default)

Wire shape (matches `BridgeRuntimeState` Pydantic model):

    {
      "connected": true,
      "subscribed": true,
      "team_id": "...",
      "session_id": "...",
      "last_heartbeat": 1715260000.0,
      "last_error": null,
      "writer_pid": 12345
    }

Staleness: the reader compares the file's `last_heartbeat` (or mtime as
a fallback) against the `freshness_seconds` threshold. Beyond that, the
state is rendered as ``stale`` in the UI rather than ``connected`` —
the writer process may have died without cleanup.

Atomicity: writes use the standard tempfile-then-rename pattern so a
concurrent reader never sees a partial file.
"""
from __future__ import annotations

import logging
import os
import tempfile
import time
from pathlib import Path
from typing import Any

from pydantic import BaseModel

logger = logging.getLogger(__name__)


DEFAULT_STATE_PATH = Path.home() / ".harbormaster" / "bridge-state.json"
DEFAULT_FRESHNESS_SECONDS = 30


class BridgeRuntimeState(BaseModel):
    """Snapshot of the live FleetQ bridge runtime as the MCP process sees it."""

    connected: bool = False
    """True after a successful register; False after disconnect / register failure."""

    subscribed: bool = False
    """True after the relay's pusher_internal:subscription_succeeded fires."""

    team_id: str | None = None
    session_id: str | None = None

    last_heartbeat: float | None = None
    """Monotonic epoch seconds (time.time()) of last successful register or heartbeat."""

    last_error: str | None = None
    """Most recent error string from register / heartbeat / subscribe; None on success."""

    writer_pid: int | None = None
    """PID of the process that wrote this file. Diagnostic only."""


class BridgeRuntimeView(BaseModel):
    """What the UI route returns. Adds derived staleness flag + age."""

    state: BridgeRuntimeState
    stale: bool = False
    """True when last_heartbeat is older than freshness_seconds (or missing)."""

    age_seconds: float | None = None
    """Wall-clock seconds since last_heartbeat. None when state has never been written."""

    state_file_present: bool = False
    """True when the state file exists on disk."""


class BridgeStateWriter:
    """Atomic-writes BridgeRuntimeState to disk. Owned by the MCP process.

    All public methods swallow exceptions and log at warning level — the
    writer must never crash the heartbeat thread or the relay.
    """

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or _resolve_state_path()
        self._state = BridgeRuntimeState()

    @property
    def state(self) -> BridgeRuntimeState:
        return self._state

    def update(self, **fields: Any) -> None:
        """Partial update + write. ``last_heartbeat`` defaults to now() when
        ``connected=True`` is being set, unless explicitly provided."""
        if fields.get("connected") and "last_heartbeat" not in fields:
            fields["last_heartbeat"] = time.time()
        self._state = self._state.model_copy(update=fields)
        self._state = self._state.model_copy(update={"writer_pid": os.getpid()})
        self._write()

    def mark_disconnected(self, error: str | None = None) -> None:
        self.update(connected=False, subscribed=False, last_error=error)

    def _write(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            payload = self._state.model_dump_json()
            # tempfile-then-rename so readers never see partial JSON
            with tempfile.NamedTemporaryFile(
                "w",
                dir=str(self.path.parent),
                prefix=".bridge-state.",
                suffix=".tmp",
                delete=False,
            ) as f:
                f.write(payload)
                tmp_path = Path(f.name)
            os.replace(tmp_path, self.path)
        except Exception as e:  # noqa: BLE001 - writer must never raise
            logger.warning(
                "BridgeStateWriter: failed to write %s (%s)", self.path, e
            )


def read_bridge_state(
    path: Path | None = None,
    *,
    freshness_seconds: int = DEFAULT_FRESHNESS_SECONDS,
    now: float | None = None,
) -> BridgeRuntimeView:
    """Read the current bridge state file and decorate it with staleness.

    Returns a default-constructed view (everything False/None) when the
    file is missing or malformed. Never raises — the UI must always be
    able to render *something*.
    """
    state_path = path or _resolve_state_path()
    current_time = now if now is not None else time.time()

    if not state_path.exists():
        return BridgeRuntimeView(
            state=BridgeRuntimeState(),
            stale=False,
            age_seconds=None,
            state_file_present=False,
        )

    try:
        raw = state_path.read_text(encoding="utf-8")
        state = BridgeRuntimeState.model_validate_json(raw)
    except Exception as e:  # noqa: BLE001 - corrupt file shouldn't break UI
        logger.warning(
            "read_bridge_state: failed to parse %s (%s) — returning empty view",
            state_path,
            e,
        )
        return BridgeRuntimeView(
            state=BridgeRuntimeState(),
            stale=True,
            age_seconds=None,
            state_file_present=True,
        )

    age: float | None
    stale: bool
    if state.last_heartbeat is None:
        age = None
        stale = True
    else:
        age = max(0.0, current_time - state.last_heartbeat)
        stale = age > freshness_seconds

    return BridgeRuntimeView(
        state=state,
        stale=stale,
        age_seconds=age,
        state_file_present=True,
    )


def _resolve_state_path() -> Path:
    """Honour HARBORMASTER_BRIDGE_STATE_FILE so tests can redirect."""
    override = os.environ.get("HARBORMASTER_BRIDGE_STATE_FILE", "").strip()
    return Path(override) if override else DEFAULT_STATE_PATH

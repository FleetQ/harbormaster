"""v10.0.0a7 / v11.0.0a1: MCP-call event log.

v10 shipped this as an in-process ring buffer. v11.0.0a1 swaps the
storage layer to a SQLite-backed `NetworkStore` so events survive
restarts. The public surface (`network_log.record/recent/subscribe/...`)
is preserved so call sites in routes.py don't need to change.

Caller-project propagation (v11.0.0a1): when a tool call originates
from another project's session — recorded via
`current_caller_project()` — the `caller` field becomes that project
name. Otherwise it falls back to "operator" (the existing default).
"""
from __future__ import annotations

import contextvars
from typing import Literal

from harbormaster.ui.network_store import (
    NetworkEvent,
    NetworkStore,
)

# Allowed tool names. Keep this in sync with what
# `harbormaster.tools.dispatcher.SAFE_FOR_PARALLEL` exposes — the v7
# audit confirmed these are the user-visible MCP entry points that
# carry an inter-project semantic (caller-project → target-project).
NetworkTool = Literal[
    "ask_project",
    "delegate_task",
    "fan_out_ask",
    "recall_qa",
]

NetworkStatus = Literal["start", "ok", "error"]


# Caller-project context: set by request middleware when an MCP call
# arrives carrying an `X-Caller-Project` header (v11.0.0a1). Falls
# back to "operator" when unset.
_caller_project: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "harbormaster_caller_project", default=None,
)


def set_caller_project(name: str | None) -> contextvars.Token[str | None]:
    """Bind the calling project for the current async context. Returns
    a Token the caller should pass to `reset_caller_project()` on exit
    so context state doesn't leak between requests."""
    return _caller_project.set(name)


def reset_caller_project(token: contextvars.Token[str | None]) -> None:
    _caller_project.reset(token)


def current_caller_project() -> str | None:
    return _caller_project.get()


# Backwards-compat alias. Some test files reference `_MCPCallLog`
# directly to construct a custom-capacity instance — point them at
# `NetworkStore` so the test API stays stable.
_MCPCallLog = NetworkStore


# Module-level singleton, reachable via
# `from harbormaster.ui.network_log import network_log`. Uses the
# default DB path at `~/.harbormaster/network_log.db` unless the env
# override `HARBORMASTER_NETWORK_LOG_DB` is set (tests use this to
# point at a tmp file).
network_log = NetworkStore()


__all__ = [
    "NetworkEvent",
    "NetworkStatus",
    "NetworkStore",
    "NetworkTool",
    "_MCPCallLog",
    "current_caller_project",
    "network_log",
    "reset_caller_project",
    "set_caller_project",
]

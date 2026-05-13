"""Async delegate job subsystem (v22.0.0a2).

Public surface:

- :class:`Job` — typed view over one row in ``delegated_jobs``.
- :class:`JobStore` — thread-safe SQLite-backed CRUD.
- :class:`JobWorker` — background thread that picks ``queued`` rows
  and dispatches them through :func:`harbormaster.tools._helpers.run_backend`.
- :func:`get_subsystem` — lazy module-level singleton that wires store
  and worker against the loaded config. Idempotent; safe to call from
  any MCP tool handler.

The subsystem is fully self-contained: no asyncio-loop ownership, no
startup hook in :mod:`harbormaster.server`. The first call to a tool
that needs an async job (``delegate_task(mode='async')`` or
``get_delegated_task``) initialises it. Restart recovery runs once at
that moment — any ``running`` row from a previous process is marked
``failed`` with reason ``server_restart``.
"""
from __future__ import annotations

from harbormaster.jobs.broadcaster import JobEventBroadcaster
from harbormaster.jobs.store import Clarification, Job, JobStore
from harbormaster.jobs.subsystem import get_subsystem, shutdown_subsystem
from harbormaster.jobs.worker import JobWorker

__all__ = [
    "Clarification", "Job", "JobStore", "JobWorker", "JobEventBroadcaster",
    "get_subsystem", "shutdown_subsystem",
]

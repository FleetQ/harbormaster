"""TTL + mtime memoization for ``GET /api/projects`` (v7.0.0a6).

The dashboard polls ``/api/projects`` on every page load (and again
on the periodic refresh). For installs with 20+ projects the
``discover_projects()`` walk dominates request latency — most of the
work is filesystem stat + git log + manifest detection that hasn't
changed since the last call.

This cache memoises the rendered ``list[ProjectInfo].as_dict()`` payload
under a TTL (default 60s) AND invalidates when any tracked project
directory's top-level mtime changes. Concurrent reads are
``threading.Lock`` serialised — the worker pool is small and the
critical section is short, so a re-entrant lock would be overkill.

Naming note: the existing ``ManifestCache`` in
``harbormaster.graph.cache`` memoises ``ProjectManifest`` rows for the
graph view. This is a separate cache for a separate payload; kept in
its own module per the v7 phase plan.
"""
from __future__ import annotations

import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_TTL_SECONDS = 60.0


@dataclass(frozen=True)
class _CacheEntry:
    payload: list[dict[str, object]]
    cached_at: float          # monotonic seconds
    mtime_signature: tuple[int, ...]  # tuple of project-dir mtime_ns


class ProjectsCache:
    """TTL + mtime-keyed memo for the /api/projects payload.

    Invariants:
      * ``get(builder, project_dirs)`` is thread-safe.
      * Cache hit only when (a) within TTL AND (b) mtime signature
        of every tracked project_dirs entry matches.
      * A single missing/unreadable directory invalidates the cache —
        we'd rather rebuild than serve stale.
    """

    def __init__(self, ttl_seconds: float = DEFAULT_TTL_SECONDS) -> None:
        if ttl_seconds < 0:
            raise ValueError("ttl_seconds must be non-negative")
        self._ttl = ttl_seconds
        self._entry: _CacheEntry | None = None
        self._lock = threading.Lock()
        # Stats — useful for diagnostics tests / future telemetry.
        self.hits = 0
        self.misses = 0

    def _signature(self, project_dirs: Sequence[Path]) -> tuple[int, ...]:
        """Return a tuple of mtime_ns for the listed dirs.
        Missing/unreadable dirs contribute -1 so that a deleted dir
        is still a signature change (cache invalidates)."""
        out: list[int] = []
        for d in project_dirs:
            try:
                out.append(d.stat().st_mtime_ns)
            except OSError:
                out.append(-1)
        return tuple(out)

    def get(
        self,
        builder: Callable[[], list[dict[str, object]]],
        project_dirs: Sequence[Path],
        *,
        now: Callable[[], float] = time.monotonic,
    ) -> list[dict[str, object]]:
        """Return cached payload when fresh; otherwise call ``builder``
        and store the result.

        ``builder`` is called inside the cache lock — concurrent
        readers will wait for the rebuild rather than each running
        their own. This is appropriate for a single-process UI;
        cross-process caching would need a different design.
        """
        signature = self._signature(project_dirs)
        with self._lock:
            now_t = now()
            entry = self._entry
            if (
                entry is not None
                and (now_t - entry.cached_at) < self._ttl
                and entry.mtime_signature == signature
            ):
                self.hits += 1
                return entry.payload
            payload = builder()
            self._entry = _CacheEntry(
                payload=payload,
                cached_at=now_t,
                mtime_signature=signature,
            )
            self.misses += 1
            return payload

    def invalidate(self) -> None:
        """Drop the cached entry. Useful for tests + admin actions
        (e.g. an operator just registered a new project)."""
        with self._lock:
            self._entry = None


# v7.0.0a6: language → Tailwind color mapping for the dashboard badge.
# The mapping is data, not template logic — kept here so the badge
# renderer (template) and any future API consumer agree.
LANGUAGE_BADGE_COLORS: dict[str, str] = {
    "python": "bg-blue-900/40 text-blue-300 border-blue-800",
    "typescript": "bg-yellow-900/40 text-yellow-200 border-yellow-800",
    "javascript": "bg-yellow-900/40 text-yellow-200 border-yellow-800",
    "php": "bg-purple-900/40 text-purple-200 border-purple-800",
    "rust": "bg-orange-900/40 text-orange-200 border-orange-800",
    "go": "bg-cyan-900/40 text-cyan-200 border-cyan-800",
    "ruby": "bg-rose-900/40 text-rose-200 border-rose-800",
    "unknown": "bg-gray-800 text-gray-500 border-gray-700",
}


def language_badge_class(language: str | None) -> str:
    """Return the Tailwind class string for a language badge.
    Falls back to the 'unknown' bucket for None / empty / unmapped."""
    key = (language or "unknown").lower()
    return LANGUAGE_BADGE_COLORS.get(key, LANGUAGE_BADGE_COLORS["unknown"])


# Convenience: extract project_dirs from ProjectInfo objects without
# importing ProjectInfo here (keeps this module dependency-free for
# easier unit testing).
def project_dirs_from_infos(infos: list[Any]) -> list[Path]:
    """Pull `.path` (Path) from a list of ProjectInfo objects."""
    out: list[Path] = []
    for p in infos:
        path = getattr(p, "path", None)
        if isinstance(path, Path):
            out.append(path)
        elif isinstance(path, str):
            out.append(Path(path))
    return out

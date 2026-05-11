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

v21.0.0a8: optional cross-process backing file at
``~/.harbormaster/projects_cache.json``. When ``persist_path`` is set,
the cache survives process restart and is shared with peer harbormaster
processes (UI + MCP). Writes are atomic via tmpfile + ``os.rename``,
serialised across processes by ``fcntl.flock``.

Naming note: the existing ``ManifestCache`` in
``harbormaster.graph.cache`` memoises ``ProjectManifest`` rows for the
graph view. This is a separate cache for a separate payload; kept in
its own module per the v7 phase plan.
"""
from __future__ import annotations

import contextlib
import json
import os
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_TTL_SECONDS = 60.0


def default_persist_path() -> Path:
    """Return the canonical cross-process cache file path.

    Honours the ``HARBORMASTER_PROJECTS_CACHE`` env var (matching the
    ``HARBORMASTER_NETWORK_LOG_DB`` / ``HARBORMASTER_MEMORY_REVISIONS_DB``
    convention from v11). Tests redirect this in ``tests/conftest.py``
    so persistence doesn't leak across the real ``~/.harbormaster/``.
    """
    override = os.environ.get("HARBORMASTER_PROJECTS_CACHE", "").strip()
    if override:
        return Path(override).expanduser()
    return Path.home() / ".harbormaster" / "projects_cache.json"


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

    v21.0.0a8: when ``persist_path`` is set, the cache also reads and
    writes a JSON file shared with peer processes. The file uses
    *wall-clock* timestamps (``time.time()``) so freshness comparisons
    across processes are coherent. Writes are atomic (tmpfile +
    ``os.rename``) and serialised by an advisory ``fcntl.flock``.
    """

    def __init__(
        self,
        ttl_seconds: float = DEFAULT_TTL_SECONDS,
        *,
        persist_path: Path | None = None,
    ) -> None:
        if ttl_seconds < 0:
            raise ValueError("ttl_seconds must be non-negative")
        self._ttl = ttl_seconds
        self._entry: _CacheEntry | None = None
        self._lock = threading.Lock()
        self._persist_path = persist_path
        if persist_path is not None:
            persist_path.parent.mkdir(parents=True, exist_ok=True)
        # Stats — useful for diagnostics tests / future telemetry.
        self.hits = 0
        self.misses = 0
        # v21.0.0a8 cross-process bookkeeping.
        self.file_hits = 0
        self.file_misses = 0

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

    def _load_from_file(self, signature: tuple[int, ...]) -> _CacheEntry | None:
        """Read the on-disk cache; return None if missing, stale,
        unreadable, or signature-mismatched."""
        if self._persist_path is None or not self._persist_path.exists():
            return None
        try:
            with self._persist_path.open("r", encoding="utf-8") as fh:
                raw = json.load(fh)
            cached_at = float(raw["cached_at"])
            payload = raw["payload"]
            file_sig = tuple(int(x) for x in raw["mtime_signature"])
        except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
            return None
        # Wall-clock TTL check (file timestamps are wall-clock).
        if (time.time() - cached_at) >= self._ttl:
            return None
        if file_sig != signature:
            return None
        if not isinstance(payload, list):
            return None
        return _CacheEntry(
            payload=payload,
            cached_at=cached_at,
            mtime_signature=signature,
        )

    def _write_to_file(self, entry: _CacheEntry) -> None:
        """Atomically persist ``entry`` to the on-disk cache.

        Serialised across processes by ``fcntl.flock`` on a lock
        sidecar file. Best-effort: persistence failures are silently
        swallowed so a read-only home dir doesn't crash the UI.
        """
        if self._persist_path is None:
            return
        try:
            import fcntl  # POSIX-only; matches harbormaster's target platforms
        except ImportError:
            fcntl = None  # type: ignore[assignment]
        lock_path = self._persist_path.with_suffix(self._persist_path.suffix + ".lock")
        tmp_path = self._persist_path.with_suffix(self._persist_path.suffix + ".tmp")
        body = json.dumps(
            {
                "cached_at": entry.cached_at,
                "mtime_signature": list(entry.mtime_signature),
                "payload": entry.payload,
            },
            separators=(",", ":"),
        )
        try:
            lock_fh: Any = None
            try:
                if fcntl is not None:
                    lock_fh = open(lock_path, "w")  # noqa: SIM115 — manual close after rename
                    fcntl.flock(lock_fh.fileno(), fcntl.LOCK_EX)
                with tmp_path.open("w", encoding="utf-8") as fh:
                    fh.write(body)
                    fh.flush()
                    with contextlib.suppress(OSError):
                        os.fsync(fh.fileno())
                os.replace(tmp_path, self._persist_path)
            finally:
                if lock_fh is not None:
                    try:
                        if fcntl is not None:
                            fcntl.flock(lock_fh.fileno(), fcntl.LOCK_UN)
                    finally:
                        lock_fh.close()
        except OSError:
            return

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
        cross-process caching is best-effort (see persist_path).
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
            # In-process entry is stale or missing — try the
            # cross-process file before paying for a discovery walk.
            file_entry = self._load_from_file(signature)
            if file_entry is not None:
                # Rebase the in-process cached_at onto monotonic time
                # so subsequent in-proc hits use the same TTL clock.
                self._entry = _CacheEntry(
                    payload=file_entry.payload,
                    cached_at=now_t,
                    mtime_signature=signature,
                )
                self.file_hits += 1
                return file_entry.payload
            self.file_misses += 1
            payload = builder()
            wall_clock_now = time.time()
            self._entry = _CacheEntry(
                payload=payload,
                cached_at=now_t,
                mtime_signature=signature,
            )
            # Persist with wall-clock time so peer processes can
            # evaluate freshness without sharing the monotonic origin.
            self._write_to_file(
                _CacheEntry(
                    payload=payload,
                    cached_at=wall_clock_now,
                    mtime_signature=signature,
                )
            )
            self.misses += 1
            return payload

    def invalidate(self) -> None:
        """Drop the cached entry. Useful for tests + admin actions
        (e.g. an operator just registered a new project)."""
        with self._lock:
            self._entry = None
        # Also delete the cross-process file so peers don't serve
        # stale data on their next miss.
        if self._persist_path is not None:
            with contextlib.suppress(OSError):
                self._persist_path.unlink()


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

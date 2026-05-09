"""mtime-keyed cache for ManifestParser results.

`ManifestCache.get(path)` returns a cached `ProjectManifest` for the
project at `path` when the manifest file's mtime is unchanged since
the cached entry was produced. Otherwise it re-parses and refreshes
the cache. Cache miss + parser miss (no manifest) is also memoised
to avoid re-stat'ing missing files on every request.

Single-process in-memory cache; not shared across `harbormaster-mcp`
and `harbormaster-ui` processes (each holds its own). That's fine —
parsing is fast and the cache exists to avoid repeating work within a
single process under bursty UI requests.
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from pathlib import Path

from harbormaster.graph.parser import ProjectManifest, parse_project

logger = logging.getLogger("harbormaster.graph.cache")


@dataclass(frozen=True)
class _Entry:
    """Cache entry. `manifest` is None when no parser matched the path
    (we still cache the negative result to skip re-stat'ing)."""

    manifest_file: Path | None
    mtime_ns: int  # 0 when manifest_file is None
    manifest: ProjectManifest | None


class ManifestCache:
    """Thread-safe in-memory ManifestParser memo."""

    def __init__(self) -> None:
        self._entries: dict[Path, _Entry] = {}
        self._lock = threading.Lock()

    def get(self, path: Path) -> ProjectManifest | None:
        """Return the manifest for `path`, parsing iff the cache is
        missing or stale. Stale = manifest file mtime newer than the
        cached entry.
        """
        path = path.resolve()
        cached = self._entries.get(path)

        if cached is not None and cached.manifest_file is not None:
            try:
                current_mtime = cached.manifest_file.stat().st_mtime_ns
            except OSError:
                # File vanished — invalidate.
                cached = None
                with self._lock:
                    self._entries.pop(path, None)
            else:
                if current_mtime == cached.mtime_ns:
                    return cached.manifest

        if cached is not None and cached.manifest_file is None:
            # Negative cache hit; we don't re-check unless the caller
            # explicitly invalidates(). Saves O(parsers) stat calls.
            return None

        manifest = parse_project(path)
        with self._lock:
            if manifest is None:
                self._entries[path] = _Entry(
                    manifest_file=None, mtime_ns=0, manifest=None
                )
            else:
                manifest_path = Path(manifest.manifest_file)
                try:
                    mtime = manifest_path.stat().st_mtime_ns
                except OSError:
                    mtime = 0
                self._entries[path] = _Entry(
                    manifest_file=manifest_path,
                    mtime_ns=mtime,
                    manifest=manifest,
                )
        return manifest

    def invalidate(self, path: Path | None = None) -> None:
        """Drop one entry (or all when path is None). The next get()
        re-parses."""
        with self._lock:
            if path is None:
                self._entries.clear()
            else:
                self._entries.pop(path.resolve(), None)

    def __len__(self) -> int:
        return len(self._entries)

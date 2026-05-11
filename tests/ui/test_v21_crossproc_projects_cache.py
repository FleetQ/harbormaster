"""Cross-process projects cache (v21.0.0a8).

Validates the v21 extension of ``ProjectsCache``:

  * cache survives process restart (a fresh ProjectsCache instance
    pointed at the same persist file reads the previous payload)
  * the on-disk file is written atomically (no half-written JSON)
  * mtime-signature change invalidates both in-process and on-disk
  * 60s TTL is respected (wall-clock for the file)
  * two reader instances see consistent data after one writer
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from harbormaster.ui.manifest_cache import ProjectsCache


@pytest.fixture
def project_dirs(tmp_path: Path) -> list[Path]:
    """Two synthetic project dirs with stable mtimes."""
    dirs = [tmp_path / "alpha", tmp_path / "beta"]
    for d in dirs:
        d.mkdir()
    return dirs


@pytest.fixture
def persist_path(tmp_path: Path) -> Path:
    return tmp_path / "cache.json"


def _payload_v1() -> list[dict[str, object]]:
    return [{"name": "alpha", "version": 1}, {"name": "beta", "version": 1}]


def test_cache_survives_process_restart(
    project_dirs: list[Path], persist_path: Path,
) -> None:
    """First ProjectsCache writes the file; second instance (simulating
    a process restart) reads from the file without invoking the builder."""
    cache_a = ProjectsCache(persist_path=persist_path)
    calls_a = 0

    def build_a() -> list[dict[str, object]]:
        nonlocal calls_a
        calls_a += 1
        return _payload_v1()

    payload_a = cache_a.get(build_a, project_dirs)
    assert calls_a == 1
    assert persist_path.exists()
    assert payload_a == _payload_v1()

    # Simulate restart — fresh ProjectsCache, same persist path.
    cache_b = ProjectsCache(persist_path=persist_path)
    calls_b = 0

    def build_b() -> list[dict[str, object]]:
        nonlocal calls_b
        calls_b += 1
        return [{"name": "should-not-be-served"}]

    payload_b = cache_b.get(build_b, project_dirs)
    assert calls_b == 0  # File hit — builder NOT invoked.
    assert payload_b == _payload_v1()
    assert cache_b.file_hits == 1


def test_on_disk_file_is_valid_json(
    project_dirs: list[Path], persist_path: Path,
) -> None:
    """Atomic write contract: the persisted file is always parseable
    (no half-written file even though we write to tmp + rename)."""
    cache = ProjectsCache(persist_path=persist_path)
    cache.get(lambda: _payload_v1(), project_dirs)

    raw = json.loads(persist_path.read_text())
    assert "cached_at" in raw
    assert "mtime_signature" in raw
    assert raw["payload"] == _payload_v1()


def test_mtime_change_invalidates_file_cache(
    project_dirs: list[Path], persist_path: Path,
) -> None:
    """If a project dir's mtime changes between processes, the second
    process must NOT serve the on-disk cache."""
    cache_a = ProjectsCache(persist_path=persist_path)
    cache_a.get(lambda: _payload_v1(), project_dirs)

    # Bump mtime by touching one of the project dirs.
    (project_dirs[0] / "marker").write_text("x")

    cache_b = ProjectsCache(persist_path=persist_path)
    rebuilds = 0

    def rebuild() -> list[dict[str, object]]:
        nonlocal rebuilds
        rebuilds += 1
        return [{"name": "alpha", "version": 2}]

    payload = cache_b.get(rebuild, project_dirs)
    assert rebuilds == 1, "mtime change should force rebuild"
    assert payload == [{"name": "alpha", "version": 2}]


def test_ttl_respected_for_file_cache(
    project_dirs: list[Path], persist_path: Path,
) -> None:
    """When the TTL has expired (wall-clock), a fresh reader rebuilds."""
    cache_a = ProjectsCache(ttl_seconds=0.05, persist_path=persist_path)
    cache_a.get(lambda: _payload_v1(), project_dirs)

    time.sleep(0.1)  # past TTL

    cache_b = ProjectsCache(ttl_seconds=0.05, persist_path=persist_path)
    rebuilds = 0

    def rebuild() -> list[dict[str, object]]:
        nonlocal rebuilds
        rebuilds += 1
        return [{"name": "fresh"}]

    payload = cache_b.get(rebuild, project_dirs)
    assert rebuilds == 1, "expired wall-clock TTL should force rebuild"
    assert payload == [{"name": "fresh"}]


def test_two_readers_see_consistent_data(
    project_dirs: list[Path], persist_path: Path,
) -> None:
    """One writer process produces the cache; two reader processes (in
    miniature: two fresh ProjectsCache instances) both observe the same
    payload from the shared file."""
    writer = ProjectsCache(persist_path=persist_path)
    writer.get(lambda: _payload_v1(), project_dirs)

    def _no_build() -> list[dict[str, object]]:
        raise AssertionError("builder must not be invoked on file hit")

    reader_x = ProjectsCache(persist_path=persist_path)
    reader_y = ProjectsCache(persist_path=persist_path)

    payload_x = reader_x.get(_no_build, project_dirs)
    payload_y = reader_y.get(_no_build, project_dirs)

    assert payload_x == payload_y == _payload_v1()
    assert reader_x.file_hits == 1
    assert reader_y.file_hits == 1


def test_invalidate_removes_on_disk_file(
    project_dirs: list[Path], persist_path: Path,
) -> None:
    """invalidate() must clear the cross-process file so peer processes
    don't serve stale data on their next miss."""
    cache = ProjectsCache(persist_path=persist_path)
    cache.get(lambda: _payload_v1(), project_dirs)
    assert persist_path.exists()

    cache.invalidate()
    assert not persist_path.exists()


def test_corrupt_file_does_not_crash_readers(
    project_dirs: list[Path], persist_path: Path,
) -> None:
    """If the cache file is corrupt (truncated JSON, bad encoding,
    etc.), readers gracefully fall back to the builder."""
    persist_path.parent.mkdir(parents=True, exist_ok=True)
    persist_path.write_text("{not valid json")

    cache = ProjectsCache(persist_path=persist_path)
    payload = cache.get(lambda: _payload_v1(), project_dirs)
    assert payload == _payload_v1()
    # Recovery: after the failed read, the cache should overwrite the
    # corrupt file with a valid one.
    json.loads(persist_path.read_text())

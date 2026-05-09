"""Tests for harbormaster.graph.cache.ManifestCache."""
from __future__ import annotations

import os
import time
from pathlib import Path

from harbormaster.graph.cache import ManifestCache


def _write_manifest(path: Path, name: str = "x", deps: tuple[str, ...] = ()) -> None:
    deps_repr = ", ".join(f'"{d}"' for d in deps)
    (path / "pyproject.toml").write_text(
        f'[project]\nname = "{name}"\ndependencies = [{deps_repr}]\n'
    )


def test_cache_returns_parsed_manifest_on_first_get(tmp_path: Path):
    _write_manifest(tmp_path, "alpha")
    cache = ManifestCache()
    m = cache.get(tmp_path)
    assert m is not None
    assert m.name == "alpha"
    assert len(cache) == 1


def test_cache_serves_subsequent_gets_from_memo(tmp_path: Path, monkeypatch):
    _write_manifest(tmp_path, "alpha")
    cache = ManifestCache()
    m1 = cache.get(tmp_path)

    # Replace the parser to detect second call; cache must NOT call it.
    from harbormaster.graph import parser
    called = {"n": 0}
    real = parser.parse_project

    def spy(p):
        called["n"] += 1
        return real(p)

    monkeypatch.setattr("harbormaster.graph.cache.parse_project", spy)
    m2 = cache.get(tmp_path)
    assert m2 == m1
    assert called["n"] == 0  # stat only, no re-parse


def test_cache_invalidates_on_mtime_change(tmp_path: Path):
    _write_manifest(tmp_path, "alpha", deps=("a",))
    cache = ManifestCache()
    m1 = cache.get(tmp_path)
    assert m1 is not None
    assert m1.deps == ("a",)

    # Bump mtime by writing new content.
    time.sleep(0.01)
    _write_manifest(tmp_path, "alpha", deps=("a", "b"))
    # Force a different mtime even if the FS resolution is too coarse.
    new_time = m1.manifest_file
    os.utime(new_time, (time.time() + 1, time.time() + 1))

    m2 = cache.get(tmp_path)
    assert m2 is not None
    assert m2.deps == ("a", "b")


def test_cache_negative_caching_for_empty_dirs(tmp_path: Path):
    cache = ManifestCache()
    assert cache.get(tmp_path) is None
    # Same get must NOT raise and must NOT re-stat (negative cached).
    assert cache.get(tmp_path) is None
    assert len(cache) == 1


def test_cache_invalidate_all(tmp_path: Path):
    _write_manifest(tmp_path, "alpha")
    cache = ManifestCache()
    cache.get(tmp_path)
    assert len(cache) == 1
    cache.invalidate()
    assert len(cache) == 0


def test_cache_invalidate_one(tmp_path: Path):
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    _write_manifest(tmp_path / "a", "a-app")
    _write_manifest(tmp_path / "b", "b-app")

    cache = ManifestCache()
    cache.get(tmp_path / "a")
    cache.get(tmp_path / "b")
    assert len(cache) == 2
    cache.invalidate(tmp_path / "a")
    assert len(cache) == 1


# --- lockfile-aware caching (v2.0.0a1) ----------------------------------


def test_cache_invalidates_on_lockfile_mtime_change(tmp_path: Path):
    """Editing the lockfile (without touching the manifest) must
    invalidate the cache so the new transitive deps are picked up."""
    _write_manifest(tmp_path, "alpha", deps=("a",))
    (tmp_path / "uv.lock").write_text(
        '[[package]]\nname = "a"\nversion = "1"\n'
    )
    cache = ManifestCache()
    m1 = cache.get(tmp_path)
    assert m1 is not None
    assert m1.transitive_deps == ("a",)

    time.sleep(0.01)
    (tmp_path / "uv.lock").write_text(
        '[[package]]\nname = "a"\nversion = "1"\n'
        '[[package]]\nname = "b"\nversion = "1"\n'
    )
    os.utime(tmp_path / "uv.lock", (time.time() + 1, time.time() + 1))

    m2 = cache.get(tmp_path)
    assert m2 is not None
    assert set(m2.transitive_deps) == {"a", "b"}


def test_cache_no_lockfile_does_not_re_parse(tmp_path: Path, monkeypatch):
    """When no lockfile exists, the cache must still hit on second
    get() without re-parsing — the lockfile-mtime probe must skip."""
    _write_manifest(tmp_path, "alpha")
    cache = ManifestCache()
    cache.get(tmp_path)

    from harbormaster.graph import parser
    real = parser.parse_project
    called = {"n": 0}

    def spy(p):
        called["n"] += 1
        return real(p)

    monkeypatch.setattr("harbormaster.graph.cache.parse_project", spy)
    cache.get(tmp_path)
    assert called["n"] == 0

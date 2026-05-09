"""Unit tests for v7.0.0a6 ProjectsCache + language_badge helper.

Covers:
  * Cache hit within TTL with unchanged signature
  * Cache miss after TTL expiry
  * Cache miss when mtime signature changes (file touched)
  * Cache miss when a tracked dir is deleted
  * Builder is called exactly once even under concurrent get()
  * Stats counters update correctly
  * invalidate() drops the cached entry
  * language_badge_class returns expected class strings
  * JS LANGUAGE_BADGE_CLASSES mirrors the Python table
"""
from __future__ import annotations

import re
import threading
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from harbormaster.config import HarbormasterConfig, ProjectsConfig
from harbormaster.ui.app import create_app
from harbormaster.ui.manifest_cache import (
    DEFAULT_TTL_SECONDS,
    LANGUAGE_BADGE_COLORS,
    ProjectsCache,
    language_badge_class,
    project_dirs_from_infos,
)

# --- ProjectsCache: cache hit / miss ----------------------------------


def test_cache_hit_within_ttl_with_unchanged_signature(
    tmp_path: Path,
) -> None:
    cache = ProjectsCache(ttl_seconds=10.0)
    d = tmp_path / "p1"
    d.mkdir()

    calls = {"n": 0}

    def builder() -> list[dict[str, object]]:
        calls["n"] += 1
        return [{"name": "p1"}]

    fake_now = [100.0]

    def now() -> float:
        return fake_now[0]

    out1 = cache.get(builder, [d], now=now)
    out2 = cache.get(builder, [d], now=now)
    assert out1 == out2 == [{"name": "p1"}]
    assert calls["n"] == 1
    assert cache.hits == 1
    assert cache.misses == 1


def test_cache_miss_after_ttl_expiry(tmp_path: Path) -> None:
    cache = ProjectsCache(ttl_seconds=10.0)
    d = tmp_path / "p1"
    d.mkdir()

    calls = {"n": 0}

    def builder() -> list[dict[str, object]]:
        calls["n"] += 1
        return [{"name": "p1", "call": calls["n"]}]

    fake_now = [100.0]

    def now() -> float:
        return fake_now[0]

    cache.get(builder, [d], now=now)
    fake_now[0] = 100.0 + 11.0  # past TTL
    cache.get(builder, [d], now=now)
    assert calls["n"] == 2
    assert cache.misses == 2


def test_cache_miss_when_signature_changes(tmp_path: Path) -> None:
    """Touching a tracked dir flips its mtime → next get rebuilds."""
    cache = ProjectsCache(ttl_seconds=999.0)
    d = tmp_path / "p1"
    d.mkdir()

    calls = {"n": 0}

    def builder() -> list[dict[str, object]]:
        calls["n"] += 1
        return [{"name": "p1"}]

    cache.get(builder, [d])
    # Force a clearly different mtime — touching may produce same ns
    # on coarse filesystems.
    import os
    os.utime(d, (1.0, 1.0))
    cache.get(builder, [d])
    os.utime(d, (2.0, 2.0))
    cache.get(builder, [d])
    assert calls["n"] == 3


def test_cache_miss_when_dir_deleted(tmp_path: Path) -> None:
    cache = ProjectsCache(ttl_seconds=999.0)
    d = tmp_path / "p1"
    d.mkdir()

    calls = {"n": 0}

    def builder() -> list[dict[str, object]]:
        calls["n"] += 1
        return [{"name": "p1"}]

    cache.get(builder, [d])
    d.rmdir()
    cache.get(builder, [d])
    assert calls["n"] == 2


def test_invalidate_drops_entry(tmp_path: Path) -> None:
    cache = ProjectsCache(ttl_seconds=999.0)
    d = tmp_path / "p1"
    d.mkdir()
    calls = {"n": 0}

    def builder() -> list[dict[str, object]]:
        calls["n"] += 1
        return []

    cache.get(builder, [d])
    cache.invalidate()
    cache.get(builder, [d])
    assert calls["n"] == 2


def test_negative_ttl_raises() -> None:
    with pytest.raises(ValueError):
        ProjectsCache(ttl_seconds=-1.0)


def test_default_ttl_is_60_seconds() -> None:
    """Locked-in invariant — bumping the default needs a deliberate edit."""
    assert DEFAULT_TTL_SECONDS == 60.0


# --- ProjectsCache: concurrency ---------------------------------------


def test_builder_called_once_under_concurrent_get(tmp_path: Path) -> None:
    """Two threads simultaneously requesting an empty cache: builder
    must run once (lock-protected). Both threads see the same payload."""
    cache = ProjectsCache(ttl_seconds=999.0)
    d = tmp_path / "p1"
    d.mkdir()

    calls = {"n": 0}
    barrier = threading.Barrier(2)
    builder_started = threading.Event()

    def slow_builder() -> list[dict[str, object]]:
        builder_started.set()
        # Hold the lock long enough for the second thread to attempt entry.
        import time
        time.sleep(0.05)
        calls["n"] += 1
        return [{"call": calls["n"]}]

    results: list[list[dict[str, object]]] = [[], []]

    def worker(idx: int) -> None:
        barrier.wait()
        results[idx] = cache.get(slow_builder, [d])

    t1 = threading.Thread(target=worker, args=(0,))
    t2 = threading.Thread(target=worker, args=(1,))
    t1.start()
    t2.start()
    t1.join()
    t2.join()
    assert calls["n"] == 1
    # Both threads got the SAME cached payload (one ran builder, one
    # waited and got the cached result on the next iteration).
    assert results[0] == results[1]


# --- language badge ----------------------------------------------------


@pytest.mark.parametrize(
    "lang, expected_substr",
    [
        ("python", "blue-300"),
        ("typescript", "yellow-200"),
        ("javascript", "yellow-200"),
        ("php", "purple-200"),
        ("rust", "orange-200"),
        ("go", "cyan-200"),
        ("ruby", "rose-200"),
        ("unknown", "gray-500"),
        (None, "gray-500"),
        ("", "gray-500"),
        ("Python", "blue-300"),  # case-insensitive
        ("nonexistent-lang", "gray-500"),  # falls back to unknown
    ],
)
def test_language_badge_class(lang: str | None, expected_substr: str) -> None:
    assert expected_substr in language_badge_class(lang)


def test_language_badge_classes_match_python_table() -> None:
    """The JS LANGUAGE_BADGE_CLASSES dict in dashboard.html must mirror
    the Python LANGUAGE_BADGE_COLORS dict — keep them in lock-step or
    the badge will render an unstyled/wrong color when tested by
    Playwright vs. unit test."""
    template = (
        Path(__file__).parent.parent.parent
        / "src"
        / "harbormaster"
        / "ui"
        / "templates"
        / "dashboard.html"
    ).read_text(encoding="utf-8")

    # Pull the JS dict block by simple regex; we only need it to
    # contain every key from the Python table.
    match = re.search(
        r"const LANGUAGE_BADGE_CLASSES\s*=\s*\{([^}]+)\}",
        template,
        flags=re.DOTALL,
    )
    assert match is not None, "LANGUAGE_BADGE_CLASSES JS dict not found"
    js_block = match.group(1)
    for py_key in LANGUAGE_BADGE_COLORS:
        # JS keys are bare identifiers (no quotes) — match `<key>:`.
        assert (
            re.search(rf"\b{re.escape(py_key)}\s*:", js_block) is not None
        ), f"language {py_key!r} present in Python table but missing from JS dict"


# --- /api/projects integration ----------------------------------------


def _seed_project(parent: Path, name: str) -> Path:
    """Create a discoverable project (needs .git or CLAUDE.md)."""
    p = parent / name
    p.mkdir()
    (p / "CLAUDE.md").write_text("# seed")
    return p


def test_api_projects_uses_cache_within_ttl(tmp_path: Path) -> None:
    """Two back-to-back GET /api/projects must return identical
    payloads; the underlying ProjectsCache hits on the second call."""
    pdir = tmp_path / "projects"
    pdir.mkdir()
    _seed_project(pdir, "p1")

    cfg = HarbormasterConfig(
        projects=ProjectsConfig(glob=[str(pdir / "*")]),
    )
    app = create_app(cfg)
    client = TestClient(app)

    r1 = client.get("/api/projects")
    r2 = client.get("/api/projects")
    assert r1.status_code == 200 == r2.status_code
    assert r1.json() == r2.json()
    assert any(p["name"] == "p1" for p in r1.json())


# --- project_dirs_from_infos -------------------------------------------


def test_project_dirs_from_infos_extracts_paths() -> None:
    class _FakeInfo:
        def __init__(self, p: Path) -> None:
            self.path = p

    out = project_dirs_from_infos(
        [_FakeInfo(Path("/tmp/a")), _FakeInfo(Path("/tmp/b"))]
    )
    assert out == [Path("/tmp/a"), Path("/tmp/b")]


def test_project_dirs_from_infos_handles_string_paths() -> None:
    class _FakeInfo:
        def __init__(self, p: str) -> None:
            self.path = p

    out = project_dirs_from_infos([_FakeInfo("/tmp/a")])
    assert out == [Path("/tmp/a")]


def test_project_dirs_from_infos_skips_objects_without_path() -> None:
    class _NoPath:
        pass

    assert project_dirs_from_infos([_NoPath()]) == []


# --- template assertion ------------------------------------------------


def test_dashboard_template_renders_language_badge_block() -> None:
    cfg = HarbormasterConfig()
    client = TestClient(create_app(cfg))
    r = client.get("/")
    assert r.status_code == 200
    # Badge element + JS helper present.
    assert "languageBadgeClass(p.language)" in r.text
    assert "p.language && p.language !== 'unknown'" in r.text
    assert "function languageBadgeClass" in r.text

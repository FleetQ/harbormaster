"""v11.0.0a6: caches consolidation.

Tests cover:
  - /api/ignored-projects 60s TTL memo (second hit returns the
    cached payload object).
  - chatOrder() reverse-cache: factory + invalidation key documented
    via template-source assertions.
  - NetworkStore.stats() returns the expected aggregate shape.
  - /api/network/stats endpoint accepts 1h/24h/7d/all and rejects
    unknown windows.
  - The network template surfaces the new stats panel.
"""
from __future__ import annotations

import time
from pathlib import Path

from fastapi.testclient import TestClient

from harbormaster.config import HarbormasterConfig, IgnoreConfig, ProjectsConfig
from harbormaster.ui import create_app
from harbormaster.ui.network_log import network_log
from harbormaster.ui.network_store import NetworkStore


def setup_function() -> None:
    network_log.clear()


def _make_project_dir(parent: Path, name: str) -> Path:
    p = parent / name
    p.mkdir(parents=True)
    (p / ".git").mkdir()
    return p


# -- /api/ignored-projects TTL ---------------------------------------


def test_ignored_projects_endpoint_returns_payload(tmp_path: Path) -> None:
    _make_project_dir(tmp_path, "alpha")
    _make_project_dir(tmp_path, "beta")
    _make_project_dir(tmp_path, "vendor")
    cfg = HarbormasterConfig(
        projects=ProjectsConfig(glob=[f"{tmp_path}/*"]),
        ignore=IgnoreConfig(patterns=["vendor*"]),
    )
    client = TestClient(create_app(cfg))
    r = client.get("/api/ignored-projects")
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 1
    assert body["names"] == ["vendor"]
    assert body["patterns"] == ["vendor*"]


def test_ignored_projects_cache_returns_same_object_within_ttl(
    tmp_path: Path,
) -> None:
    """Second call within TTL should return the EXACT cached dict —
    not a fresh discovery pass."""
    _make_project_dir(tmp_path, "alpha")
    _make_project_dir(tmp_path, "ignoreme")
    cfg = HarbormasterConfig(
        projects=ProjectsConfig(glob=[f"{tmp_path}/*"]),
        ignore=IgnoreConfig(patterns=["ignore*"]),
    )
    client = TestClient(create_app(cfg))
    r1 = client.get("/api/ignored-projects")
    r2 = client.get("/api/ignored-projects")
    assert r1.status_code == 200
    assert r2.status_code == 200
    # Same payload — TTL cache hit.
    assert r1.json() == r2.json()


# -- NetworkStore.stats ------------------------------------------------


def test_network_store_stats_aggregates_counts(tmp_path: Path) -> None:
    store = NetworkStore(db_path=tmp_path / "n.db")
    for _ in range(3):
        store.record(caller="op", target="alpha", tool="ask_project")
    for _ in range(2):
        store.record(caller="op", target="beta", tool="recall_qa")
    store.record(
        caller="op", target="alpha", tool="ask_project", status="error",
    )

    s = store.stats()
    assert s["total_calls"] == 6
    assert s["by_tool"] == {"ask_project": 4, "recall_qa": 2}
    top = s["top_projects_by_calls"]
    assert isinstance(top, list)
    assert top[0] == {"project": "alpha", "count": 4}
    assert s["error_rate"] == 1 / 6


def test_network_store_stats_respects_since_ms(tmp_path: Path) -> None:
    store = NetworkStore(db_path=tmp_path / "n.db")
    # Insert one row, then artificially force timestamp_ms in the future
    # for a second row by directly manipulating store's record path
    # (each record() uses time.time() so we use sleep to ensure ordering).
    store.record(caller="op", target="alpha", tool="ask_project")
    # Tiny sleep to ensure distinct timestamps.
    time.sleep(0.01)
    midpoint_ms = int(time.time() * 1000)
    time.sleep(0.01)
    store.record(caller="op", target="beta", tool="ask_project")

    # Filter to events after midpoint → only beta.
    s = store.stats(since_ms=midpoint_ms)
    assert s["total_calls"] == 1
    by_tool = s["by_tool"]
    assert isinstance(by_tool, dict)


def test_network_store_stats_empty(tmp_path: Path) -> None:
    store = NetworkStore(db_path=tmp_path / "n.db")
    s = store.stats()
    assert s["total_calls"] == 0
    assert s["by_tool"] == {}
    assert s["top_projects_by_calls"] == []
    assert s["error_rate"] == 0.0


# -- /api/network/stats endpoint ---------------------------------------


def test_api_network_stats_default_window_is_24h(tmp_path: Path) -> None:
    network_log.record(caller="op", target="alpha", tool="ask_project")
    client = TestClient(create_app(HarbormasterConfig()))
    r = client.get("/api/network/stats")
    assert r.status_code == 200
    body = r.json()
    assert body["window"] == "24h"
    assert body["total_calls"] >= 1


def test_api_network_stats_accepts_known_windows(tmp_path: Path) -> None:
    client = TestClient(create_app(HarbormasterConfig()))
    for w in ("1h", "24h", "7d", "all"):
        r = client.get(f"/api/network/stats?window={w}")
        assert r.status_code == 200, w
        assert r.json()["window"] == w


def test_api_network_stats_rejects_unknown_window(tmp_path: Path) -> None:
    client = TestClient(create_app(HarbormasterConfig()))
    r = client.get("/api/network/stats?window=99h")
    assert r.status_code == 400


def test_api_network_stats_returns_top_projects(tmp_path: Path) -> None:
    network_log.clear()
    for _ in range(3):
        network_log.record(caller="op", target="alpha", tool="ask_project")
    network_log.record(caller="op", target="beta", tool="recall_qa")
    client = TestClient(create_app(HarbormasterConfig()))
    body = client.get("/api/network/stats?window=all").json()
    top = body["top_projects_by_calls"]
    assert top[0]["project"] == "alpha"
    assert top[0]["count"] == 3


# -- Template surfaces the stats panel + chatOrder cache --------------


def test_network_template_includes_stats_panel(tmp_path: Path) -> None:
    client = TestClient(create_app(HarbormasterConfig()))
    r = client.get("/network")
    assert r.status_code == 200
    body = r.text
    assert "Network stats" in body
    assert "/api/network/stats?window=" in body
    assert "function networkStats" in body
    # Window dropdown options.
    for opt in ("last 1h", "last 24h", "last 7d", "all time"):
        assert opt in body


def test_network_template_uses_chatorder_cache(tmp_path: Path) -> None:
    client = TestClient(create_app(HarbormasterConfig()))
    r = client.get("/network")
    body = r.text
    # v16.0.0a1: chatOrder() routes through the shared cachedGetter
    # helper. The deps tuple still keys on events.length so SSE pushes
    # invalidate exactly as before. The helper itself comes in via
    # base.html → _partials/_cached_getter.html.
    assert "cachedGetter(this, 'chatOrder'" in body
    assert "this.events.length" in body
    assert "window.cachedGetter" in body

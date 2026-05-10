"""v14.0.0a2: distinct_sources() + /api/network/sources endpoint."""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from harbormaster.config import HarbormasterConfig
from harbormaster.ui import create_app
from harbormaster.ui.network_log import network_log
from harbormaster.ui.network_store import NetworkStore


def setup_function() -> None:
    network_log.clear()


def _seed(store: NetworkStore, callers: list[str]) -> None:
    for c in callers:
        store.record(
            caller=c, target="alpha",
            tool="ask_project", status="ok",
            question_preview="q",
        )


def test_distinct_sources_returns_unique_alphabetical(tmp_path: Path) -> None:
    db = tmp_path / "net.db"
    store = NetworkStore(db_path=db)
    _seed(store, ["operator", "harbormaster", "operator", "alpha", "harbormaster"])
    sources = store.distinct_sources(scan_limit=1000)
    assert sources == ["alpha", "harbormaster", "operator"]


def test_distinct_sources_empty_store_returns_empty_list(tmp_path: Path) -> None:
    db = tmp_path / "net.db"
    store = NetworkStore(db_path=db)
    assert store.distinct_sources() == []


def test_distinct_sources_scan_limit_applies_to_recent_window(
    tmp_path: Path,
) -> None:
    """When scan_limit=2, only the 2 most recent rows are scanned."""
    db = tmp_path / "net.db"
    store = NetworkStore(db_path=db)
    # Older rows mention 'old', newer rows mention 'new'. With scan_limit=2,
    # 'old' must NOT appear (it was scrolled out of the recency window).
    _seed(store, ["old", "old", "old", "new", "new"])
    sources = store.distinct_sources(scan_limit=2)
    assert sources == ["new"]


def test_distinct_sources_invalid_scan_limit_raises(tmp_path: Path) -> None:
    db = tmp_path / "net.db"
    store = NetworkStore(db_path=db)
    with pytest.raises(ValueError):
        store.distinct_sources(scan_limit=0)


def test_api_sources_returns_distinct_callers() -> None:
    network_log.record(
        caller="operator", target="alpha",
        tool="ask_project", status="ok",
        question_preview="q",
    )
    network_log.record(
        caller="harbormaster", target="beta",
        tool="ask_project", status="ok",
        question_preview="q",
    )
    network_log.record(
        caller="operator", target="gamma",
        tool="ask_project", status="ok",
        question_preview="q",
    )
    cfg = HarbormasterConfig()
    app = create_app(cfg)
    with TestClient(app) as client:
        r = client.get("/api/network/sources")
        assert r.status_code == 200
        body = r.json()
        assert body == {"sources": ["harbormaster", "operator"]}


def test_api_sources_rejects_out_of_range_scan_limit() -> None:
    cfg = HarbormasterConfig()
    app = create_app(cfg)
    with TestClient(app) as client:
        r = client.get("/api/network/sources?scan_limit=0")
        assert r.status_code == 400
        r = client.get("/api/network/sources?scan_limit=99999")
        assert r.status_code == 400


def test_api_sources_empty_store_returns_empty_list() -> None:
    cfg = HarbormasterConfig()
    app = create_app(cfg)
    with TestClient(app) as client:
        r = client.get("/api/network/sources")
        assert r.status_code == 200
        assert r.json() == {"sources": []}

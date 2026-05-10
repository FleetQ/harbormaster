"""v14.0.0a4 — per-host call budget endpoint + network timeline view."""
from __future__ import annotations

import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from harbormaster.config import HarbormasterConfig, HostConfig
from harbormaster.ui import create_app
from harbormaster.ui.network_log import network_log
from harbormaster.ui.network_store import NetworkStore

TEMPLATE_DIR = (
    Path(__file__).parent.parent.parent
    / "src"
    / "harbormaster"
    / "ui"
    / "templates"
)


def setup_function() -> None:
    network_log.clear()


def _read(name: str) -> str:
    return (TEMPLATE_DIR / name).read_text(encoding="utf-8")


# -- HostConfig schema -------------------------------------------------


def test_host_config_accepts_daily_call_budget() -> None:
    h = HostConfig(ssh_host="alpha.local", daily_call_budget=100)
    assert h.daily_call_budget == 100


def test_host_config_default_budget_is_none() -> None:
    h = HostConfig(ssh_host="alpha.local")
    assert h.daily_call_budget is None


def test_host_config_rejects_zero_budget() -> None:
    with pytest.raises(ValueError):
        HostConfig(ssh_host="alpha.local", daily_call_budget=0)


# -- count_by_target ---------------------------------------------------


def test_count_by_target_groups_correctly(tmp_path: Path) -> None:
    db = tmp_path / "net.db"
    store = NetworkStore(db_path=db)
    for target in ["alpha", "alpha", "beta", "alpha", "gamma"]:
        store.record(
            caller="operator", target=target,
            tool="ask_project", status="ok",
            question_preview="q",
        )
    counts = store.count_by_target()
    assert counts == {"alpha": 3, "beta": 1, "gamma": 1}


def test_count_by_target_window_filters(tmp_path: Path) -> None:
    db = tmp_path / "net.db"
    store = NetworkStore(db_path=db)
    store.record(
        caller="operator", target="alpha",
        tool="ask_project", status="ok",
        question_preview="q",
    )
    # Window in the future = no rows match.
    future = int(time.time() * 1000) + 60_000
    counts = store.count_by_target(since_ms=future)
    assert counts == {}


# -- /api/hosts/budget endpoint ---------------------------------------


def test_api_hosts_budget_reports_configured_hosts() -> None:
    cfg = HarbormasterConfig(
        hosts={
            "alpha": HostConfig(ssh_host="alpha.local", daily_call_budget=100),
            "beta": HostConfig(ssh_host="beta.local"),  # no budget
        }
    )
    # Seed network_log with calls targeting alpha + beta.
    for _ in range(10):
        network_log.record(
            caller="operator", target="alpha",
            tool="ask_project", status="ok", question_preview="q",
        )
    network_log.record(
        caller="operator", target="beta",
        tool="ask_project", status="ok", question_preview="q",
    )

    app = create_app(cfg)
    with TestClient(app) as client:
        r = client.get("/api/hosts/budget")
        assert r.status_code == 200
        body = r.json()
        assert body["window_hours"] == 24
        hosts = {h["host"]: h for h in body["hosts"]}
        # alpha: 10 / 100 = 10%
        assert hosts["alpha"]["calls_24h"] == 10
        assert hosts["alpha"]["budget"] == 100
        assert hosts["alpha"]["usage_pct"] == 10.0
        # beta: budget=null, usage_pct=null
        assert hosts["beta"]["calls_24h"] == 1
        assert hosts["beta"]["budget"] is None
        assert hosts["beta"]["usage_pct"] is None


def test_api_hosts_budget_with_no_hosts_returns_empty_list() -> None:
    cfg = HarbormasterConfig()
    app = create_app(cfg)
    with TestClient(app) as client:
        r = client.get("/api/hosts/budget")
        assert r.status_code == 200
        assert r.json() == {"window_hours": 24, "hosts": []}


def test_api_hosts_budget_excludes_unconfigured_targets() -> None:
    """A target that's hit (e.g. 'operator') but not in [hosts.*]
    must NOT appear in the budget report — budget is per-configured-host."""
    cfg = HarbormasterConfig(
        hosts={"alpha": HostConfig(ssh_host="alpha.local")}
    )
    network_log.record(
        caller="operator", target="random-project",
        tool="ask_project", status="ok", question_preview="q",
    )
    app = create_app(cfg)
    with TestClient(app) as client:
        r = client.get("/api/hosts/budget")
        body = r.json()
        # Only alpha is configured, so only alpha appears.
        hosts = {h["host"] for h in body["hosts"]}
        assert hosts == {"alpha"}


# -- Timeline UI wiring (template smoke) ------------------------------


def test_network_html_has_timeline_view_button() -> None:
    body = _read("network.html")
    assert "hm-network-view-timeline" in body
    assert "$dispatch('hm:network:view', 'timeline')" in body
    assert ">\n      Timeline\n    <" in body


def test_network_html_timeline_window_toggle_present() -> None:
    body = _read("network.html")
    # Both 1h and 24h toggle buttons.
    assert "timelineWindow = '1h'" in body
    assert "timelineWindow = '24h'" in body


def test_network_html_timeline_buckets_getter_defined() -> None:
    body = _read("network.html")
    # Computed bucket pipeline.
    assert "get timelineBuckets()" in body
    assert "get timelineMaxBucket()" in body
    assert "get timelineEventsTotal()" in body


def test_network_html_persisted_view_accepts_timeline() -> None:
    body = _read("network.html")
    # Persisted view restoration must accept 'timeline'.
    assert "saved === 'timeline'" in body


def test_network_html_timeline_renders_inline_svg() -> None:
    """No new vendored library — timeline must use inline <svg>."""
    body = _read("network.html")
    # There must be an svg with the bucket loop inside.
    assert "viewBox=" in body
    assert "<rect :x=\"i * 8\"" in body


# -- KPI cell wiring -------------------------------------------------


def test_dashboard_has_host_budget_kpi_cell() -> None:
    body = _read("dashboard.html")
    assert 'data-kpi-cell="hosts-budget"' in body
    assert "hostBudgetLabel()" in body
    assert "loadBudget()" in body

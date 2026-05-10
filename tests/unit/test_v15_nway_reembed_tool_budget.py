"""v15.0.0a4 — N-way reembed comparison + per-tool budget."""
from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from harbormaster.config import (
    BudgetConfig,
    HarbormasterConfig,
)
from harbormaster.ui import create_app


@pytest.fixture(autouse=True)
def _isolate_network_log(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> Any:
    """Per-test network_log isolation. The module-level singleton
    persists across tests; we re-init its connection from a fresh
    NetworkStore so /api/tools/budget sees a clean slate. Pattern
    cribbed from tests/ui/test_network_event_filtering.py."""
    db = tmp_path / "nlog.db"
    monkeypatch.setenv("HARBORMASTER_NETWORK_LOG_DB", str(db))
    from harbormaster.ui.network_log import network_log
    from harbormaster.ui.network_store import NetworkStore

    fresh = NetworkStore()
    network_log._conn = fresh._conn  # type: ignore[attr-defined]
    network_log._max_rows = fresh._max_rows  # type: ignore[attr-defined]
    yield
    with network_log._lock:  # type: ignore[attr-defined]
        network_log._conn.execute("DELETE FROM mcp_calls")  # type: ignore[attr-defined]
        network_log._conn.commit()  # type: ignore[attr-defined]


# -- BudgetConfig schema -----------------------------------------


def test_budget_config_default_is_empty() -> None:
    cfg = BudgetConfig()
    assert cfg.daily_call_budget_per_tool == {}


def test_budget_config_accepts_positive_budgets() -> None:
    cfg = BudgetConfig(daily_call_budget_per_tool={"ask_project": 1000})
    assert cfg.daily_call_budget_per_tool == {"ask_project": 1000}


def test_budget_config_rejects_zero_budget() -> None:
    with pytest.raises(ValueError, match="must be > 0"):
        BudgetConfig(daily_call_budget_per_tool={"ask_project": 0})


def test_budget_config_rejects_negative_budget() -> None:
    with pytest.raises(ValueError, match="must be > 0"):
        BudgetConfig(daily_call_budget_per_tool={"ask_project": -1})


def test_harbormaster_config_includes_budget_section() -> None:
    cfg = HarbormasterConfig()
    assert isinstance(cfg.budget, BudgetConfig)
    assert cfg.budget.daily_call_budget_per_tool == {}


# -- /api/tools/budget endpoint ---------------------------------


def test_api_tools_budget_returns_empty_when_no_budgets_and_no_calls(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Isolate the network_log to a per-test path so we don't pull in
    # the operator's real recent calls.
    monkeypatch.setenv("HARBORMASTER_NETWORK_LOG_DB", str(tmp_path / "nlog.db"))
    cfg = HarbormasterConfig()
    app = create_app(cfg)
    with TestClient(app) as client:
        r = client.get("/api/tools/budget")
        assert r.status_code == 200
        body = r.json()
        assert body["window_hours"] == 24
        assert body["tools"] == []


def test_api_tools_budget_lists_configured_tools_with_zero_calls(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HARBORMASTER_NETWORK_LOG_DB", str(tmp_path / "nlog.db"))
    cfg = HarbormasterConfig(
        budget=BudgetConfig(
            daily_call_budget_per_tool={"ask_project": 1000, "fan_out_ask": 100},
        ),
    )
    app = create_app(cfg)
    with TestClient(app) as client:
        r = client.get("/api/tools/budget")
        assert r.status_code == 200
        tools = {t["tool"]: t for t in r.json()["tools"]}
        assert tools["ask_project"]["budget"] == 1000
        assert tools["ask_project"]["calls_24h"] == 0
        assert tools["ask_project"]["usage_pct"] == 0.0
        assert tools["fan_out_ask"]["budget"] == 100


def test_api_tools_budget_unbudgeted_tools_appear_with_null_budget(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Tools called within the window but with no budget config still
    appear in the response (with budget=null) so the operator can see
    all activity in one place."""
    monkeypatch.setenv("HARBORMASTER_NETWORK_LOG_DB", str(tmp_path / "nlog.db"))
    from harbormaster.ui.network_log import network_log

    # Force-record one call for an unbudgeted tool.
    network_log.record(
        target="some-project", tool="recall_qa", caller="operator",
        duration_ms=12,
    )
    cfg = HarbormasterConfig()
    app = create_app(cfg)
    with TestClient(app) as client:
        r = client.get("/api/tools/budget")
        assert r.status_code == 200
        tools = {t["tool"]: t for t in r.json()["tools"]}
        assert "recall_qa" in tools
        assert tools["recall_qa"]["budget"] is None
        assert tools["recall_qa"]["usage_pct"] is None
        assert tools["recall_qa"]["calls_24h"] >= 1


# -- /api/history/reembed/runs/compare endpoint ----------------


def _fake_run(
    *, started_at: float, finished_at: float, total: int, succeeded: int,
    failed: int = 0, cancelled: int = 0, model: str = "bge-small-en-v1.5",
) -> Any:
    """Build a minimal ReembedRunRecord-like Pydantic model dump."""
    from harbormaster.history import ReembedRunRecord

    return ReembedRunRecord(
        started_at=started_at, finished_at=finished_at,
        total=total, succeeded=succeeded, failed=failed,
        cancelled=cancelled, model=model,
    )


def test_api_history_reembed_runs_compare_returns_n_runs() -> None:
    cfg = HarbormasterConfig()
    app = create_app(cfg)
    runs = [
        _fake_run(started_at=100.0, finished_at=110.0, total=10, succeeded=10),
        _fake_run(started_at=200.0, finished_at=215.0, total=12, succeeded=11, failed=1),
        _fake_run(started_at=300.0, finished_at=320.0, total=15, succeeded=14, failed=1),
        _fake_run(started_at=400.0, finished_at=445.0, total=20, succeeded=18, failed=2),
    ]
    with patch(
        "harbormaster.history.read_reembed_runs", return_value=runs,
    ), TestClient(app) as client:
        r = client.get("/api/history/reembed/runs/compare?indices=0,2,3")
        assert r.status_code == 200
        body = r.json()
        assert body["indices"] == [0, 2, 3]
        assert len(body["runs"]) == 3
        # Field "duration_seconds" carries one value per run.
        field_by_name = {f["name"]: f for f in body["fields"]}
        assert field_by_name["duration_seconds"]["values"] == [
            10.0, 20.0, 45.0,
        ]
        assert field_by_name["total"]["values"] == [10, 15, 20]
        assert field_by_name["succeeded"]["values"] == [10, 14, 18]
        assert field_by_name["failed"]["values"] == [0, 1, 2]


def test_api_history_reembed_runs_compare_supports_two_runs() -> None:
    """2-way is the minimum useful comparison — must still work."""
    cfg = HarbormasterConfig()
    app = create_app(cfg)
    runs = [
        _fake_run(started_at=100.0, finished_at=110.0, total=10, succeeded=10),
        _fake_run(started_at=200.0, finished_at=210.0, total=12, succeeded=12),
    ]
    with patch(
        "harbormaster.history.read_reembed_runs", return_value=runs,
    ), TestClient(app) as client:
        r = client.get("/api/history/reembed/runs/compare?indices=0,1")
        assert r.status_code == 200
        assert len(r.json()["runs"]) == 2


def test_api_history_reembed_runs_compare_dedups_indices() -> None:
    cfg = HarbormasterConfig()
    app = create_app(cfg)
    runs = [
        _fake_run(started_at=100.0, finished_at=110.0, total=10, succeeded=10),
        _fake_run(started_at=200.0, finished_at=210.0, total=12, succeeded=12),
    ]
    with patch(
        "harbormaster.history.read_reembed_runs", return_value=runs,
    ), TestClient(app) as client:
        r = client.get("/api/history/reembed/runs/compare?indices=0,1,1,0")
        assert r.status_code == 200
        assert r.json()["indices"] == [0, 1]


def test_api_history_reembed_runs_compare_caps_at_4() -> None:
    cfg = HarbormasterConfig()
    app = create_app(cfg)
    runs = [
        _fake_run(started_at=float(i), finished_at=float(i + 1), total=i, succeeded=i)
        for i in range(10)
    ]
    with patch(
        "harbormaster.history.read_reembed_runs", return_value=runs,
    ), TestClient(app) as client:
        r = client.get(
            "/api/history/reembed/runs/compare?indices=0,1,2,3,4",
        )
        assert r.status_code == 400
        assert "at most 4" in r.json()["detail"]


def test_api_history_reembed_runs_compare_requires_indices() -> None:
    cfg = HarbormasterConfig()
    app = create_app(cfg)
    with TestClient(app) as client:
        r = client.get("/api/history/reembed/runs/compare?indices=")
        assert r.status_code == 400


def test_api_history_reembed_runs_compare_404_on_out_of_range() -> None:
    cfg = HarbormasterConfig()
    app = create_app(cfg)
    runs = [
        _fake_run(started_at=100.0, finished_at=110.0, total=10, succeeded=10),
    ]
    with patch(
        "harbormaster.history.read_reembed_runs", return_value=runs,
    ), TestClient(app) as client:
        r = client.get("/api/history/reembed/runs/compare?indices=0,5")
        assert r.status_code == 404


def test_api_history_reembed_runs_compare_400_on_non_integer() -> None:
    cfg = HarbormasterConfig()
    app = create_app(cfg)
    with TestClient(app) as client:
        r = client.get("/api/history/reembed/runs/compare?indices=0,abc")
        assert r.status_code == 400


# -- UI wiring (template smoke) -----------------------------------


def _read_template(name: str) -> str:
    from pathlib import Path

    template_dir = (
        Path(__file__).parent.parent.parent
        / "src"
        / "harbormaster"
        / "ui"
        / "templates"
    )
    return (template_dir / name).read_text(encoding="utf-8")


def test_dashboard_template_per_tool_breakdown_panel_renders() -> None:
    body = _read_template("dashboard.html")
    assert "Per-tool · 24h" in body
    assert "x-for=\"t in (toolsBudget.tools || [])\"" in body


def test_dashboard_template_per_tool_breakdown_lazy_loaded() -> None:
    body = _read_template("dashboard.html")
    # Lazy-load wiring: first hover triggers the fetch.
    assert "showToolsBudget()" in body
    assert "_toolsBudgetLoaded" in body
    assert "if (!this._toolsBudgetLoaded)" in body


def test_dashboard_template_per_tool_polled_after_first_hover() -> None:
    body = _read_template("dashboard.html")
    # The 30s tick refreshes the per-tool data only after first hover.
    assert "if (this._toolsBudgetLoaded) this.loadToolsBudget()" in body

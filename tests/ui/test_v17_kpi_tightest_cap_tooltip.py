"""v17.0.0a4 — KPI strip tightest_cap hover tooltip.

Surfaces the v16.a5 per-project budget's `tightest_cap_axis`
breakdown on the KPI strip's host-budget cell. Operators see
which axis (per-host / per-tool / per-project) is bottlenecking
without opening the projects-budget endpoint.

Reuses the existing v15.a4 tooltip pattern — same anchor cell,
same lazy-load-on-hover semantics; v17.a4 only EXTENDS the
tooltip body with a per-axis breakdown above the existing
per-tool list.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from harbormaster.config import HarbormasterConfig, ProjectsConfig
from harbormaster.ui.app import create_app


@pytest.fixture
def kpi_client(tmp_path: Path) -> TestClient:
    (tmp_path / "projects").mkdir(parents=True, exist_ok=True)
    cfg = HarbormasterConfig(
        projects=ProjectsConfig(glob=[str(tmp_path / "projects" / "*")]),
    )
    return TestClient(create_app(cfg))


# ---- 1. Page render: new tooltip markup -------------------------------


def test_tightest_tooltip_markup_present(kpi_client: TestClient) -> None:
    """The v17.a4 tooltip block is anchored to the existing v15.a4
    hover cell. Pin the new data-* hooks so style refactors don't
    break the contract."""
    body = kpi_client.get("/").text
    assert "data-kpi-tightest-tooltip" in body
    assert "data-tightest-axis-row" in body
    # The tightest-axis row carries data-tightest-axis (host/tool/
    # project) and data-tightest-axis-winner (true/false).
    assert ":data-tightest-axis=" in body
    assert ":data-tightest-axis-winner=" in body


def test_tooltip_uses_existing_pattern(kpi_client: TestClient) -> None:
    """v17.a4 must reuse the v15.a4 hover cell + tooltip container —
    not introduce a second pattern. The host-budget KPI cell still
    drives the show via @mouseenter showToolsBudget(); the existing
    per-tool list still renders below the new axis list."""
    body = kpi_client.get("/").text
    # Same anchor cell.
    assert 'data-kpi-cell="hosts-budget"' in body
    # Same hover binding into the same factory method.
    assert "showToolsBudget()" in body
    # Existing per-tool list still present.
    assert "Per-tool · 24h" in body


# ---- 2. Factory state + helper functions ------------------------------


def test_tightest_breakdown_factory_state(kpi_client: TestClient) -> None:
    body = kpi_client.get("/").text
    # New state: tightestBreakdown holds {host, axes}; loaded-for
    # marker prevents redundant refetches when the same worst host
    # persists across hovers.
    assert "tightestBreakdown:" in body
    assert "_tightestLoadedFor" in body


def test_tightest_breakdown_helper_exists(kpi_client: TestClient) -> None:
    body = kpi_client.get("/").text
    # The lazy-loader helper. Wired into the v15.a4 showToolsBudget
    # so the same hover-trigger that fetches per-tool also fetches
    # the per-project breakdown for the worst host.
    assert "_loadTightestBreakdown" in body
    # Calls the v16.a5 endpoint scoped to the worst host.
    assert "/api/projects/budget" in body


def test_tightest_axis_highlighted(kpi_client: TestClient) -> None:
    """The row whose usage_pct is closest to cap is marked
    `is_tightest = true` and rendered with a warning class. The
    template uses :class binding on `row.is_tightest`."""
    body = kpi_client.get("/").text
    assert "is_tightest" in body
    assert "row.is_tightest ? 'text-warning font-bold' : 'text-foreground-muted'" in body


# ---- 3. Endpoint shape consumed by the helper -------------------------


def test_projects_budget_endpoint_returns_axis_data(
    kpi_client: TestClient,
) -> None:
    """The renderer requires `tightest_cap_axis` per project row.
    v16.a5 added the field; v17.a4 is the first UI consumer — pin
    the wire shape so the hover doesn't silently regress."""
    # The endpoint requires a configured host; without one we expect 404.
    r = kpi_client.get("/api/projects/budget?host=missing")
    assert r.status_code == 404


def test_projects_budget_axis_shape_with_configured_host(
    tmp_path: Path,
) -> None:
    """End-to-end: configure a host with a project, hit the endpoint,
    verify the row carries `tightest_cap_axis` (the field the v17.a4
    breakdown helper would surface as the per-project axis)."""
    from harbormaster.config import (
        HarbormasterConfig,
        HostConfig,
        HostProjectBudget,
        ProjectsConfig,
    )

    (tmp_path / "projects").mkdir(parents=True, exist_ok=True)
    cfg = HarbormasterConfig(
        projects=ProjectsConfig(glob=[str(tmp_path / "projects" / "*")]),
        hosts={
            "myhost": HostConfig(
                ssh_host="myhost.example",
                daily_call_budget=100,
                projects={
                    "harbormaster": HostProjectBudget(
                        daily_call_budget=10,
                    ),
                },
            ),
        },
    )
    client = TestClient(create_app(cfg))
    r = client.get("/api/projects/budget?host=myhost")
    assert r.status_code == 200
    body = r.json()
    assert body["host"] == "myhost"
    assert len(body["projects"]) == 1
    row = body["projects"][0]
    assert row["project"] == "harbormaster"
    assert row["budget"] == 10
    # tightest_cap_axis is the field v17.a4's helper consumes.
    assert "tightest_cap_axis" in row
    # 10 (project) is the tightest of {100 host, 10 project}; tool
    # cap is None (not configured).
    assert row["tightest_cap"] == 10
    assert row["tightest_cap_axis"] == "project"

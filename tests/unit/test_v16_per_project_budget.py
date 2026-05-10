"""v16.0.0a5 — per-project budget (carry-over #9).

Closes the budget triad:

  per-host (v14.0.0a4)
+ per-tool (v15.0.0a4)
+ per-project (this)

Tightest-cap-wins logic combines all three when checking. The new
``GET /api/projects/budget?host=<name>`` endpoint surfaces the
per-project consumption + budget AND the tightest cap actually in
effect (with `tightest_cap_axis` recording which axis won).
"""
from __future__ import annotations

import time

from fastapi.testclient import TestClient

from harbormaster.config import (
    BudgetConfig,
    HarbormasterConfig,
    HostConfig,
    HostProjectBudget,
)
from harbormaster.ui import create_app
from harbormaster.ui.network_log import network_log


def _seed_call(target: str, tool: str = "ask_project", at_ms: int | None = None) -> None:
    """Insert one synthetic mcp_calls row directly via the singleton's
    private API. Same shape used by tests/ui/test_network_event_filtering.
    """
    if at_ms is None:
        at_ms = int(time.time() * 1000)
    with network_log._lock:  # type: ignore[attr-defined]
        network_log._conn.execute(  # type: ignore[attr-defined]
            "INSERT INTO mcp_calls "
            "(timestamp, source, target, tool, status, "
            " duration_ms, question_preview) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (at_ms, "operator", target, tool, "ok", 10, ""),
        )
        network_log._conn.commit()  # type: ignore[attr-defined]


# ---- Item 1: HostProjectBudget config model -------------------------------


def test_host_project_budget_parses_from_nested_toml() -> None:
    cfg = HarbormasterConfig(
        hosts={
            "alpha": HostConfig(
                ssh_host="alpha.local",
                projects={
                    "frontend": HostProjectBudget(daily_call_budget=50),
                    "backend": HostProjectBudget(daily_call_budget=100),
                },
            ),
        },
    )
    assert cfg.hosts["alpha"].projects["frontend"].daily_call_budget == 50
    assert cfg.hosts["alpha"].projects["backend"].daily_call_budget == 100


def test_host_project_budget_defaults_empty_dict() -> None:
    cfg = HarbormasterConfig(
        hosts={"alpha": HostConfig(ssh_host="alpha.local")},
    )
    assert cfg.hosts["alpha"].projects == {}


def test_host_project_budget_must_be_positive() -> None:
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        HostProjectBudget(daily_call_budget=0)
    with pytest.raises(ValidationError):
        HostProjectBudget(daily_call_budget=-1)


# ---- Item 2: /api/projects/budget endpoint --------------------------------


def test_api_projects_budget_404_when_host_unknown() -> None:
    app = create_app(HarbormasterConfig())
    with TestClient(app) as client:
        r = client.get("/api/projects/budget?host=missing")
        assert r.status_code == 404


def test_api_projects_budget_returns_empty_list_when_no_projects() -> None:
    cfg = HarbormasterConfig(
        hosts={"alpha": HostConfig(ssh_host="alpha.local")},
    )
    app = create_app(cfg)
    with TestClient(app) as client:
        r = client.get("/api/projects/budget?host=alpha")
        assert r.status_code == 200
        body = r.json()
        assert body["host"] == "alpha"
        assert body["window_hours"] == 24
        assert body["projects"] == []


def test_api_projects_budget_returns_per_project_consumption() -> None:
    cfg = HarbormasterConfig(
        hosts={
            "alpha": HostConfig(
                ssh_host="alpha.local",
                projects={
                    "frontend": HostProjectBudget(daily_call_budget=10),
                    "backend": HostProjectBudget(daily_call_budget=20),
                },
            ),
        },
    )
    app = create_app(cfg)
    # Seed: 3 calls to frontend, 1 to backend, 5 to an unrelated target.
    for _ in range(3):
        _seed_call("frontend")
    _seed_call("backend")
    for _ in range(5):
        _seed_call("operator")

    with TestClient(app) as client:
        r = client.get("/api/projects/budget?host=alpha")
        assert r.status_code == 200
        body = r.json()
        by_name = {p["project"]: p for p in body["projects"]}
        assert by_name["frontend"]["calls_24h"] == 3
        assert by_name["frontend"]["budget"] == 10
        assert by_name["frontend"]["usage_pct"] == 30.0
        assert by_name["backend"]["calls_24h"] == 1
        assert by_name["backend"]["budget"] == 20
        assert by_name["backend"]["usage_pct"] == 5.0


# ---- Item 3: tightest-cap-wins arithmetic --------------------------------


def test_tightest_cap_wins_picks_per_project_when_smallest() -> None:
    cfg = HarbormasterConfig(
        hosts={
            "alpha": HostConfig(
                ssh_host="alpha.local",
                daily_call_budget=1000,
                projects={
                    "frontend": HostProjectBudget(daily_call_budget=10),
                },
            ),
        },
        budget=BudgetConfig(
            daily_call_budget_per_tool={"ask_project": 500},
        ),
    )
    app = create_app(cfg)
    with TestClient(app) as client:
        r = client.get("/api/projects/budget?host=alpha")
        body = r.json()
        front = body["projects"][0]
        assert front["tightest_cap"] == 10
        assert front["tightest_cap_axis"] == "project"


def test_tightest_cap_wins_picks_per_host_when_smallest() -> None:
    cfg = HarbormasterConfig(
        hosts={
            "alpha": HostConfig(
                ssh_host="alpha.local",
                daily_call_budget=5,
                projects={
                    "frontend": HostProjectBudget(daily_call_budget=100),
                },
            ),
        },
        budget=BudgetConfig(
            daily_call_budget_per_tool={"ask_project": 500},
        ),
    )
    app = create_app(cfg)
    with TestClient(app) as client:
        r = client.get("/api/projects/budget?host=alpha")
        front = r.json()["projects"][0]
        assert front["tightest_cap"] == 5
        assert front["tightest_cap_axis"] == "host"


def test_tightest_cap_wins_picks_per_tool_when_smallest() -> None:
    cfg = HarbormasterConfig(
        hosts={
            "alpha": HostConfig(
                ssh_host="alpha.local",
                daily_call_budget=1000,
                projects={
                    "frontend": HostProjectBudget(daily_call_budget=100),
                },
            ),
        },
        budget=BudgetConfig(
            daily_call_budget_per_tool={"ask_project": 7},
        ),
    )
    app = create_app(cfg)
    with TestClient(app) as client:
        r = client.get("/api/projects/budget?host=alpha")
        front = r.json()["projects"][0]
        assert front["tightest_cap"] == 7
        assert front["tightest_cap_axis"] == "tool"


def test_tightest_cap_null_when_no_axis_set() -> None:
    cfg = HarbormasterConfig(
        hosts={
            "alpha": HostConfig(
                ssh_host="alpha.local",
                projects={
                    "frontend": HostProjectBudget(),
                },
            ),
        },
    )
    app = create_app(cfg)
    with TestClient(app) as client:
        r = client.get("/api/projects/budget?host=alpha")
        front = r.json()["projects"][0]
        assert front["tightest_cap"] is None
        assert front["tightest_cap_axis"] is None


# ---- Item 4: count_by_target_filtered helper -----------------------------


def test_count_by_target_filtered_returns_zero_for_unseen_targets() -> None:
    _seed_call("frontend")
    counts = network_log.count_by_target_filtered(
        targets=["frontend", "backend", "ghost"], since_ms=None,
    )
    assert counts == {"frontend": 1, "backend": 0, "ghost": 0}


def test_count_by_target_filtered_empty_targets_returns_empty_dict() -> None:
    counts = network_log.count_by_target_filtered(
        targets=[], since_ms=None,
    )
    assert counts == {}

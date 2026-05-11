"""v21.0.0a2: Q&A History tab + Settings budget form.

Pins:
  - Q&A History tab placeholder is gone; functional template + Alpine
    factory `projectQaHistory(...)` is wired in.
  - Settings tab includes a budget form with a save handler and the
    `projectSettings(...)` Alpine factory.
  - `PUT /api/projects/{name}/budget` writes `[budget]
    daily_call_budget = N` into `<project>/.harbormaster.toml`, null
    removes the key, and re-emits other tables intact.
  - `GET /api/projects/{name}/budget` returns the three-axis effective
    cap (per_host / per_tool / per_project + tightest_*).
  - Path-traversal returns 400.
"""
from __future__ import annotations

import tomllib
from pathlib import Path

from fastapi.testclient import TestClient

from harbormaster.config import (
    BudgetConfig,
    HarbormasterConfig,
    HostConfig,
    HostProjectBudget,
    ProjectsConfig,
)
from harbormaster.ui import create_app

TEMPLATE_PATH = (
    Path(__file__).parent.parent.parent
    / "src"
    / "harbormaster"
    / "ui"
    / "templates"
    / "project_detail.html"
)


def _read_template() -> str:
    return TEMPLATE_PATH.read_text()


# --- Template assertions -------------------------------------------------


def test_qa_history_placeholder_removed() -> None:
    """The v19.0.0a5 placeholder copy must be gone — Q&A history now
    has a real search form + results list."""
    src = _read_template()
    assert "full impl in v19.0.0a5" not in src
    assert 'projectQaHistory(' in src
    # The functional surface — search input + result template.
    assert 'id="hm-qa-history-results"' in src
    assert "x-for=\"entry in results\"" in src


def test_qa_history_uses_single_quote_factory_mount() -> None:
    """v19.a9 lesson: factory mount uses single-quoted bind, never
    `tojson` in double-quoted attribute."""
    src = _read_template()
    assert "projectQaHistory('{{ project.name | e" in src
    assert "projectSettings('{{ project.name | e" in src


def test_settings_tab_includes_budget_form() -> None:
    """Settings now exposes an editable budget form alongside
    metadata."""
    src = _read_template()
    assert 'projectSettings(' in src
    assert 'id="hm-project-budget-form"' in src
    # The save handler is wired up.
    assert 'save()' in src
    # The three-axis effective cap line is rendered.
    assert "per-host" in src
    assert "per-tool" in src
    assert "per-project" in src


def test_alpine_factories_defined() -> None:
    """Both `projectQaHistory` and `projectSettings` factory functions
    must be defined as Alpine controllers."""
    src = _read_template()
    assert "function projectQaHistory(projectName)" in src
    assert "function projectSettings(projectName)" in src


# --- Backend endpoint behaviour -----------------------------------------


def _make_project_dir(parent: Path, name: str) -> Path:
    p = parent / name
    p.mkdir(parents=True)
    (p / ".git").mkdir()
    return p


def _config(tmp_path: Path, **kwargs: object) -> HarbormasterConfig:
    return HarbormasterConfig(
        projects=ProjectsConfig(glob=[f"{tmp_path}/*"]),
        **kwargs,  # type: ignore[arg-type]
    )


def test_put_budget_writes_toml_with_value(tmp_path: Path) -> None:
    p = _make_project_dir(tmp_path, "alpha")
    client = TestClient(create_app(_config(tmp_path)))
    r = client.put(
        "/api/projects/alpha/budget",
        json={"daily_call_budget": 42},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["per_project"] == 42
    assert body["tightest_cap_axis"] == "per_project"
    assert body["tightest_cap_value"] == 42

    toml_path = p / ".harbormaster.toml"
    assert toml_path.is_file()
    parsed = tomllib.loads(toml_path.read_text())
    assert parsed == {"budget": {"daily_call_budget": 42}}


def test_put_budget_removes_key_when_null(tmp_path: Path) -> None:
    p = _make_project_dir(tmp_path, "alpha")
    (p / ".harbormaster.toml").write_text(
        "[budget]\ndaily_call_budget = 50\n", encoding="utf-8",
    )
    client = TestClient(create_app(_config(tmp_path)))
    r = client.put(
        "/api/projects/alpha/budget",
        json={"daily_call_budget": None},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["per_project"] is None

    parsed = tomllib.loads((p / ".harbormaster.toml").read_text())
    assert "budget" not in parsed


def test_put_budget_preserves_other_tables(tmp_path: Path) -> None:
    """Writing the budget value must not clobber `[markdown]` or other
    top-level tables already in `.harbormaster.toml`."""
    p = _make_project_dir(tmp_path, "alpha")
    (p / ".harbormaster.toml").write_text(
        "[markdown]\nstrict = false\n", encoding="utf-8",
    )
    client = TestClient(create_app(_config(tmp_path)))
    r = client.put(
        "/api/projects/alpha/budget",
        json={"daily_call_budget": 25},
    )
    assert r.status_code == 200, r.text

    parsed = tomllib.loads((p / ".harbormaster.toml").read_text())
    assert parsed["markdown"]["strict"] is False
    assert parsed["budget"]["daily_call_budget"] == 25


def test_get_budget_reports_three_axes(tmp_path: Path) -> None:
    _make_project_dir(tmp_path, "alpha")
    cfg = HarbormasterConfig(
        projects=ProjectsConfig(glob=[f"{tmp_path}/*"]),
        hosts={
            "h1": HostConfig(
                ssh_host="h1",
                daily_call_budget=1000,
                projects={"alpha": HostProjectBudget(daily_call_budget=500)},
            ),
        },
        budget=BudgetConfig(
            daily_call_budget_per_tool={"ask_project": 200},
        ),
    )
    client = TestClient(create_app(cfg))
    r = client.get("/api/projects/alpha/budget")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["per_host"] == 1000
    assert body["per_tool"] == 200
    # No .harbormaster.toml override; falls back to per-host project cell.
    assert body["per_project"] == 500
    # Tightest cap wins → per_tool=200.
    assert body["tightest_cap_axis"] == "per_tool"
    assert body["tightest_cap_value"] == 200


def test_get_budget_prefers_toml_over_host_cell(tmp_path: Path) -> None:
    """When `.harbormaster.toml` `[budget]` is set, it overrides the
    `[hosts.*.projects.<name>]` cell."""
    p = _make_project_dir(tmp_path, "alpha")
    (p / ".harbormaster.toml").write_text(
        "[budget]\ndaily_call_budget = 33\n", encoding="utf-8",
    )
    cfg = HarbormasterConfig(
        projects=ProjectsConfig(glob=[f"{tmp_path}/*"]),
        hosts={
            "h1": HostConfig(
                ssh_host="h1",
                projects={"alpha": HostProjectBudget(daily_call_budget=500)},
            ),
        },
    )
    client = TestClient(create_app(cfg))
    r = client.get("/api/projects/alpha/budget")
    assert r.status_code == 200, r.text
    assert r.json()["per_project"] == 33


def test_put_budget_rejects_zero_and_negative(tmp_path: Path) -> None:
    _make_project_dir(tmp_path, "alpha")
    client = TestClient(create_app(_config(tmp_path)))
    for bad in (0, -5):
        r = client.put(
            "/api/projects/alpha/budget",
            json={"daily_call_budget": bad},
        )
        assert r.status_code == 400, (bad, r.text)


def test_put_budget_path_traversal_400(tmp_path: Path) -> None:
    _make_project_dir(tmp_path, "alpha")
    client = TestClient(create_app(_config(tmp_path)))
    r = client.put(
        "/api/projects/..%2Fevil/budget",
        json={"daily_call_budget": 10},
    )
    # FastAPI may decode the path before validation — both 400 and 404
    # are acceptable (rejected before any filesystem touch).
    assert r.status_code in (400, 404)


def test_get_budget_no_overrides_returns_nulls(tmp_path: Path) -> None:
    _make_project_dir(tmp_path, "alpha")
    client = TestClient(create_app(_config(tmp_path)))
    r = client.get("/api/projects/alpha/budget")
    assert r.status_code == 200
    body = r.json()
    assert body["per_host"] is None
    assert body["per_tool"] is None
    assert body["per_project"] is None
    assert body["tightest_cap_axis"] is None
    assert body["tightest_cap_value"] is None

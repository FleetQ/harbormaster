"""v17.0.0a3 — N-way reembed compare UI + sparkline integration.

Closes two carry-overs from v16:
  * #4 N-way reembed compare UI: the v15.a4 endpoint
    `/api/history/reembed/runs/compare` exists but no UI consumed
    it; this phase adds multi-select checkboxes + a comparison
    panel.
  * #3 sparklineHtml integration: the v16.a4 helper exists but no
    UI consumed it; the comparison panel renders per-numeric-field
    sparklines via `sparklineCell(field)`.

Test layers:
  1. Page render: the new markup hooks (data-*) are present.
  2. Action wiring: Alpine factory state + helper functions exist.
  3. Endpoint shape: server compare endpoint returns the field-array
     shape the renderer consumes.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from harbormaster.config import HarbormasterConfig, ProjectsConfig
from harbormaster.ui.app import create_app


@pytest.fixture
def compare_client(tmp_path: Path) -> TestClient:
    (tmp_path / "projects").mkdir(parents=True, exist_ok=True)
    cfg = HarbormasterConfig(
        projects=ProjectsConfig(glob=[str(tmp_path / "projects" / "*")]),
    )
    return TestClient(create_app(cfg))


# ---- 1. Page render: new markup hooks present --------------------------


def test_compare_action_bar_markup(compare_client: TestClient) -> None:
    """The compare action bar appears once selection ≥ 1."""
    body = compare_client.get("/").text
    assert "data-reembed-compare-bar" in body
    assert "data-reembed-compare-trigger" in body
    # Per-row checkbox in the runs table.
    assert "data-reembed-compare-checkbox" in body


def test_compare_panel_markup(compare_client: TestClient) -> None:
    body = compare_client.get("/").text
    assert "data-reembed-compare-panel" in body
    assert "data-reembed-compare-table" in body
    assert "data-reembed-compare-sparkline" in body


def test_compare_panel_consumes_v15_endpoint(compare_client: TestClient) -> None:
    """The renderer must hit the v15.a4 endpoint by URL — the URL is
    the contract; refactors that change it would break the panel."""
    body = compare_client.get("/").text
    assert "/api/history/reembed/runs/compare" in body


def test_sparkline_helper_loaded_globally(compare_client: TestClient) -> None:
    """The v16.a4 sparklineHtml partial must be loaded by the base
    template so the dashboard can use it without re-importing.
    Pinned here because v17.a3 is the first consumer."""
    body = compare_client.get("/").text
    # The function name appears in the partial script body and is
    # invoked from the dashboard's sparklineCell() helper.
    assert "sparklineHtml" in body
    assert "sparklineCell" in body


# ---- 2. Action wiring: Alpine state + helper functions exist -----------


def test_compare_factory_state_initialised(compare_client: TestClient) -> None:
    body = compare_client.get("/").text
    # State fields the renderer + tests rely on.
    assert "selectedRunIndices: []" in body
    assert "compareOpen: false" in body
    assert "compareLoading: false" in body
    # The data shape mirrors the server response:
    # { indices, runs, fields }
    assert "compareData:" in body


def test_compare_helper_functions_exist(compare_client: TestClient) -> None:
    body = compare_client.get("/").text
    assert "toggleCompareSelection" in body
    assert "clearCompareSelection" in body
    assert "loadCompareSelected" in body
    assert "formatCompareCell" in body
    assert "sparklineCell" in body


def test_compare_caps_at_4(compare_client: TestClient) -> None:
    """The UI cap of 4 (matching the server-side limit) must be
    enforced in the toggle handler so the user gets immediate
    feedback when a 5th tick is attempted."""
    body = compare_client.get("/").text
    # Either side of the cap check should reference 4.
    assert "selectedRunIndices.length >= 4" in body


# ---- 3. Endpoint shape consumed by the renderer ------------------------


def test_compare_endpoint_shape_for_renderer(
    compare_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Pin the wire shape the renderer consumes. The v15.a4 endpoint
    already exists; v17.a3 is the first UI consumer, so we lock the
    `fields` array of `{name, values}` records here too."""
    from harbormaster.history.reembed_history import ReembedRunRecord

    runs = [
        ReembedRunRecord(
            started_at=1700000000.0, finished_at=1700000010.0,
            total=10, succeeded=9, failed=1, cancelled=0, model="m-old",
        ),
        ReembedRunRecord(
            started_at=1700001000.0, finished_at=1700001008.0,
            total=12, succeeded=12, failed=0, cancelled=0, model="m-new",
        ),
        ReembedRunRecord(
            started_at=1700002000.0, finished_at=1700002009.0,
            total=11, succeeded=10, failed=0, cancelled=1, model="m-new",
        ),
    ]
    monkeypatch.setattr(
        "harbormaster.history.read_reembed_runs",
        lambda: runs,
    )

    r = compare_client.get(
        "/api/history/reembed/runs/compare?indices=0,1,2"
    )
    assert r.status_code == 200
    body = r.json()
    assert body["indices"] == [0, 1, 2]
    assert len(body["runs"]) == 3

    # Field array shape: each entry has {name, values}.
    fields_by_name = {f["name"]: f["values"] for f in body["fields"]}
    assert "duration_seconds" in fields_by_name
    assert "total" in fields_by_name
    assert "succeeded" in fields_by_name
    assert "failed" in fields_by_name
    assert "cancelled" in fields_by_name
    assert "model" in fields_by_name

    # Numeric fields the sparkline renderer consumes — exactly N
    # values per field, matching the indices list length.
    assert len(fields_by_name["total"]) == 3
    assert len(fields_by_name["duration_seconds"]) == 3
    # Numeric type so sparklineHtml accepts them.
    assert all(isinstance(v, (int, float)) for v in fields_by_name["total"])
    assert all(isinstance(v, (int, float))
               for v in fields_by_name["duration_seconds"])


def test_compare_endpoint_caps_at_4(
    compare_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The renderer's UI cap of 4 mirrors a server-side cap. Pin the
    server cap here so a UI-only relax doesn't accidentally let
    through a 5-way request."""
    from harbormaster.history.reembed_history import ReembedRunRecord

    runs = [
        ReembedRunRecord(
            started_at=float(i) * 100,
            finished_at=float(i) * 100 + 10,
            total=10,
            succeeded=10,
            failed=0,
            cancelled=0,
            model="m",
        )
        for i in range(6)
    ]
    monkeypatch.setattr(
        "harbormaster.history.read_reembed_runs",
        lambda: runs,
    )

    r = compare_client.get(
        "/api/history/reembed/runs/compare?indices=0,1,2,3,4"
    )
    assert r.status_code == 400

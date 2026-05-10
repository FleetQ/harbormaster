"""Tests for the v8.0.0a5 /api/kpi endpoint + KPI strip template.

Endpoint behaviour:
  * Returns the canonical 5-key shape on a fresh install.
  * `projects` reflects the discovered count.
  * `recent_queries` is null when [history] is disabled.
  * `bridge` is "disabled" when fleetq.enabled = false.
  * `dispatcher` is "ready" (placeholder until v9 waterfall).
  * `since_seconds` parameter is echoed back; bounds-checked.

Template:
  * 5 cells with `data-kpi-cell` attributes are present.
  * Each cell carries `:aria-label` for SR.
  * `kpiStrip()` Alpine helper is defined.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from harbormaster.config import HarbormasterConfig, ProjectsConfig
from harbormaster.ui.app import create_app


@pytest.fixture
def kpi_client(tmp_path: Path) -> TestClient:
    """A UI app with an empty project glob and history disabled."""
    (tmp_path / "projects").mkdir(parents=True, exist_ok=True)
    cfg = HarbormasterConfig(
        projects=ProjectsConfig(glob=[str(tmp_path / "projects" / "*")]),
    )
    return TestClient(create_app(cfg))


def test_kpi_endpoint_canonical_shape(kpi_client: TestClient) -> None:
    r = kpi_client.get("/api/kpi")
    assert r.status_code == 200
    body = r.json()
    for key in (
        "projects",
        "active_embeds",
        "recent_queries",
        "bridge",
        "dispatcher",
        "since_seconds",
    ):
        assert key in body, f"missing KPI key: {key}"


def test_kpi_projects_count_zero_on_empty(kpi_client: TestClient) -> None:
    body = kpi_client.get("/api/kpi").json()
    assert body["projects"] == 0


def test_kpi_active_embeds_shape(kpi_client: TestClient) -> None:
    body = kpi_client.get("/api/kpi").json()
    ae = body["active_embeds"]
    assert "phase" in ae
    assert "processed" in ae
    assert "total" in ae


def test_kpi_recent_queries_null_when_history_disabled(kpi_client: TestClient) -> None:
    body = kpi_client.get("/api/kpi").json()
    assert body["recent_queries"] is None


def test_kpi_bridge_disabled_when_fleetq_off(kpi_client: TestClient) -> None:
    body = kpi_client.get("/api/kpi").json()
    assert body["bridge"] == "disabled"


def test_kpi_dispatcher_placeholder_ready(kpi_client: TestClient) -> None:
    # v8.0.0a5 shipped this as the hardcoded "ready" placeholder; v9.0.0a2
    # replaced it with a derived state from /api/dispatcher/status.
    # Reset the singleton so this test sees a cold dispatcher (other tests
    # in the suite share the process-wide stats singleton).
    from harbormaster.fleetq import get_dispatcher_stats

    get_dispatcher_stats().reset()
    body = kpi_client.get("/api/kpi").json()
    assert body["dispatcher"] == "ready"


def test_kpi_since_seconds_echoed(kpi_client: TestClient) -> None:
    body = kpi_client.get("/api/kpi?since_seconds=600").json()
    assert body["since_seconds"] == 600


def test_kpi_since_seconds_floored_at_60(kpi_client: TestClient) -> None:
    """Below the 60s floor we still echo the requested value but the
    underlying query uses max(60, since)."""
    body = kpi_client.get("/api/kpi?since_seconds=10").json()
    assert body["since_seconds"] == 10
    # recent_queries is None here because history is disabled, but
    # endpoint should not 500.
    assert body["recent_queries"] is None


# --- template assertions ----------------------------------------------------


TEMPLATE_DIR = (
    Path(__file__).parent.parent.parent
    / "src"
    / "harbormaster"
    / "ui"
    / "templates"
)


@pytest.mark.parametrize(
    "cell_id",
    ["projects", "active-embeds", "recent-queries", "bridge", "dispatcher"],
)
def test_kpi_cell_present_in_dashboard(cell_id: str) -> None:
    src = (TEMPLATE_DIR / "dashboard.html").read_text()
    assert f'data-kpi-cell="{cell_id}"' in src, f"missing KPI cell: {cell_id}"


def test_kpi_strip_alpine_scope_defined() -> None:
    src = (TEMPLATE_DIR / "dashboard.html").read_text()
    assert "function kpiStrip()" in src
    assert "loadKpi()" in src
    assert "startPolling()" in src


def test_kpi_strip_aria_label_on_section() -> None:
    src = (TEMPLATE_DIR / "dashboard.html").read_text()
    assert 'aria-label="Dashboard at-a-glance metrics"' in src


def test_kpi_cells_bind_aria_labels() -> None:
    src = (TEMPLATE_DIR / "dashboard.html").read_text()
    # Each cell binds :aria-label for screen readers.
    for label in (
        "projects discovered",
        "Reembed phase",
        "queries in the last hour",
        "Bridge ${kpi.bridge",
        "Dispatcher ${kpi.dispatcher",
    ):
        assert label in src, f"missing aria-label phrase: {label!r}"

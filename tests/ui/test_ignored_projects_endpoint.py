"""v10.0.0a4: /api/ignored-projects endpoint + sidebar indicator.

Pins the diagnostic surface that lets operators see what's hidden by
[ignore].patterns without editing TOML to find out.
"""
from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from harbormaster.config import (
    HarbormasterConfig,
    IgnoreConfig,
    ProjectsConfig,
)
from harbormaster.ui import create_app


def _make_project_dir(parent: Path, name: str) -> Path:
    p = parent / name
    p.mkdir(parents=True)
    (p / ".git").mkdir()
    return p


def _config_with_projects(tmp_path: Path, ignore: list[str]) -> HarbormasterConfig:
    return HarbormasterConfig(
        projects=ProjectsConfig(glob=[f"{tmp_path}/*"]),
        ignore=IgnoreConfig(patterns=ignore),
    )


def test_endpoint_returns_zero_when_no_patterns(tmp_path: Path) -> None:
    _make_project_dir(tmp_path, "alpha")
    _make_project_dir(tmp_path, "beta")
    config = _config_with_projects(tmp_path, ignore=[])
    client = TestClient(create_app(config))
    r = client.get("/api/ignored-projects")
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 0
    assert body["names"] == []
    assert body["patterns"] == []


def test_endpoint_lists_filtered_projects(tmp_path: Path) -> None:
    _make_project_dir(tmp_path, "alpha")
    _make_project_dir(tmp_path, "beta-ui")
    _make_project_dir(tmp_path, "gamma-ui")
    config = _config_with_projects(tmp_path, ignore=["*-ui"])
    client = TestClient(create_app(config))
    r = client.get("/api/ignored-projects")
    body = r.json()
    assert body["count"] == 2
    assert body["names"] == ["beta-ui", "gamma-ui"]
    assert body["patterns"] == ["*-ui"]


def test_endpoint_pattern_diff_does_not_match_visible_projects(tmp_path: Path) -> None:
    """Sanity: the response excludes projects that are visible."""
    _make_project_dir(tmp_path, "alpha")
    _make_project_dir(tmp_path, "beta-ui")
    config = _config_with_projects(tmp_path, ignore=["*-ui"])
    client = TestClient(create_app(config))
    body = client.get("/api/ignored-projects").json()
    assert "alpha" not in body["names"]


def test_sidebar_markup_includes_ignored_section() -> None:
    """The base.html sidebar must declare the v10.0.0a4 ignored
    section so operators see at-a-glance what's hidden."""
    src = (
        Path(__file__).parent.parent.parent
        / "src" / "harbormaster" / "ui"
        / "templates" / "base.html"
    ).read_text()
    assert 'data-sidebar-group="ignored"' in src
    # State + loader hooked into the Alpine component.
    assert "ignored: { patterns: [], count: 0, names: [] }" in src
    assert "_loadIgnored" in src
    # Endpoint reference.
    assert "/api/ignored-projects" in src

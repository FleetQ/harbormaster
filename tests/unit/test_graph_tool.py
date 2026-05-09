"""Tests for the project_graph MCP tool + GET /api/graph endpoint."""
from __future__ import annotations

from pathlib import Path

import pytest

from harbormaster.config import HarbormasterConfig, ProjectsConfig
from harbormaster.server import build_server


def _tools_by_name(mcp):
    return {t.name: t for t in mcp._tool_manager.list_tools()}


def _make_python_project(path: Path, name: str, deps=(), description: str = "p") -> None:
    path.mkdir(parents=True, exist_ok=True)
    deps_repr = ", ".join(f'"{d}"' for d in deps)
    (path / "pyproject.toml").write_text(
        f'[project]\nname = "{name}"\nversion = "1.0"\n'
        f'description = "{description}"\n'
        f'dependencies = [{deps_repr}]\n'
    )
    (path / "CLAUDE.md").write_text("# stub for project marker")


# --- MCP tool surface ----------------------------------------------------


def test_project_graph_registered():
    mcp = build_server(HarbormasterConfig())
    assert "project_graph" in _tools_by_name(mcp)


def test_project_graph_returns_empty_on_empty_glob(tmp_path: Path):
    config = HarbormasterConfig(
        projects=ProjectsConfig(glob=[str(tmp_path / "nonexistent" / "*")])
    )
    mcp = build_server(config)
    fn = _tools_by_name(mcp)["project_graph"].fn
    out = fn()
    assert out["projects_discovered"] == 0
    assert out["manifests"] == []
    assert out["graph"]["nodes"] == []


def test_project_graph_discovers_python_projects(tmp_path: Path):
    _make_python_project(tmp_path / "alpha", "alpha")
    _make_python_project(tmp_path / "beta", "beta")
    config = HarbormasterConfig(
        projects=ProjectsConfig(glob=[str(tmp_path / "*")])
    )
    mcp = build_server(config)
    fn = _tools_by_name(mcp)["project_graph"].fn
    out = fn()
    assert out["projects_discovered"] == 2
    names = {m["name"] for m in out["manifests"]}
    assert names == {"alpha", "beta"}


def test_project_graph_creates_internal_edge(tmp_path: Path):
    _make_python_project(tmp_path / "alpha", "alpha", deps=("beta",))
    _make_python_project(tmp_path / "beta", "beta")
    config = HarbormasterConfig(
        projects=ProjectsConfig(glob=[str(tmp_path / "*")])
    )
    mcp = build_server(config)
    fn = _tools_by_name(mcp)["project_graph"].fn
    out = fn()
    edges = out["graph"]["edges"]
    assert len(edges) == 1
    assert edges[0]["src"] == "alpha"
    assert edges[0]["dst"] == "beta"


def test_project_graph_format_mermaid_emits_mermaid_field(tmp_path: Path):
    _make_python_project(tmp_path / "alpha", "alpha")
    config = HarbormasterConfig(
        projects=ProjectsConfig(glob=[str(tmp_path / "*")])
    )
    mcp = build_server(config)
    fn = _tools_by_name(mcp)["project_graph"].fn
    out = fn(format="mermaid")
    assert "mermaid" in out
    assert out["mermaid"].startswith("graph LR")
    assert 'alpha["alpha"]' in out["mermaid"]


def test_project_graph_format_json_omits_mermaid_field(tmp_path: Path):
    _make_python_project(tmp_path / "alpha", "alpha")
    config = HarbormasterConfig(
        projects=ProjectsConfig(glob=[str(tmp_path / "*")])
    )
    mcp = build_server(config)
    fn = _tools_by_name(mcp)["project_graph"].fn
    out = fn(format="json")
    assert "mermaid" not in out


# --- HTTP endpoint -------------------------------------------------------

httpx = pytest.importorskip("httpx")
fastapi = pytest.importorskip("fastapi")


def test_api_graph_endpoint_returns_json(tmp_path: Path):
    from fastapi.testclient import TestClient

    from harbormaster.ui.app import create_app

    _make_python_project(tmp_path / "alpha", "alpha", deps=("beta",))
    _make_python_project(tmp_path / "beta", "beta")
    config = HarbormasterConfig(
        projects=ProjectsConfig(glob=[str(tmp_path / "*")])
    )
    app = create_app(config)
    client = TestClient(app)

    r = client.get("/api/graph")
    assert r.status_code == 200
    data = r.json()
    assert data["projects_discovered"] == 2
    assert "mermaid" in data
    assert "graph" in data
    edge_pairs = {(e["src"], e["dst"]) for e in data["graph"]["edges"]}
    assert ("alpha", "beta") in edge_pairs


# --- transitive graph (v2.0.0a1) ----------------------------------------


def _make_python_project_with_lockfile(
    path: Path, name: str, deps: tuple[str, ...] = (), lockfile_pkgs: tuple[str, ...] = ()
) -> None:
    """Create a python project with both pyproject.toml and uv.lock."""
    _make_python_project(path, name, deps=deps)
    blocks = "\n".join(
        f'[[package]]\nname = "{p}"\nversion = "1.0.0"\n' for p in lockfile_pkgs
    )
    (path / "uv.lock").write_text(blocks + "\n")


def test_project_graph_transitive_default_off(tmp_path: Path):
    """Default behaviour preserved: lockfile data does not produce edges
    unless transitive=True."""
    _make_python_project_with_lockfile(
        tmp_path / "alpha", "alpha", deps=(), lockfile_pkgs=("beta",)
    )
    _make_python_project(tmp_path / "beta", "beta")
    config = HarbormasterConfig(
        projects=ProjectsConfig(glob=[str(tmp_path / "*")])
    )
    mcp = build_server(config)
    fn = _tools_by_name(mcp)["project_graph"].fn
    out = fn()
    assert out["graph"]["edges"] == []
    assert out["projects_with_lockfile"] == 1


def test_project_graph_transitive_on_emits_transitive_edges(tmp_path: Path):
    _make_python_project_with_lockfile(
        tmp_path / "alpha", "alpha", deps=(), lockfile_pkgs=("beta",)
    )
    _make_python_project(tmp_path / "beta", "beta")
    config = HarbormasterConfig(
        projects=ProjectsConfig(glob=[str(tmp_path / "*")])
    )
    mcp = build_server(config)
    fn = _tools_by_name(mcp)["project_graph"].fn
    out = fn(transitive=True)
    edges = out["graph"]["edges"]
    assert len(edges) == 1
    assert edges[0]["kind"] == "transitive"
    assert edges[0]["src"] == "alpha"
    assert edges[0]["dst"] == "beta"


def test_project_graph_reports_projects_with_lockfile_count(tmp_path: Path):
    _make_python_project(tmp_path / "alpha", "alpha")
    _make_python_project_with_lockfile(
        tmp_path / "beta", "beta", lockfile_pkgs=("gamma",)
    )
    config = HarbormasterConfig(
        projects=ProjectsConfig(glob=[str(tmp_path / "*")])
    )
    mcp = build_server(config)
    fn = _tools_by_name(mcp)["project_graph"].fn
    out = fn()
    assert out["projects_discovered"] == 2
    assert out["projects_with_lockfile"] == 1


def test_project_graph_manifest_includes_lockfile_field(tmp_path: Path):
    _make_python_project_with_lockfile(
        tmp_path / "alpha", "alpha", lockfile_pkgs=("beta",)
    )
    config = HarbormasterConfig(
        projects=ProjectsConfig(glob=[str(tmp_path / "*")])
    )
    mcp = build_server(config)
    fn = _tools_by_name(mcp)["project_graph"].fn
    out = fn()
    manifest = out["manifests"][0]
    assert manifest["lockfile"] is not None
    assert manifest["lockfile"].endswith("uv.lock")
    assert manifest["transitive_deps"] == ["beta"]

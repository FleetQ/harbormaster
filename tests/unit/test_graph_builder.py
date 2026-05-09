"""Tests for harbormaster.graph.builder.build_graph + Mermaid renderer."""
from __future__ import annotations

from harbormaster.graph.builder import (
    GraphEdge,
    GraphNode,
    ProjectGraph,
    build_graph,
    graph_to_mermaid,
)
from harbormaster.graph.parser import ProjectManifest


def _m(name: str, language: str = "python", deps=(), dev_deps=()) -> ProjectManifest:
    return ProjectManifest(
        name=name,
        language=language,
        path=f"/p/{name}",
        manifest_file=f"/p/{name}/pyproject.toml",
        deps=tuple(deps),
        dev_deps=tuple(dev_deps),
    )


def test_build_graph_empty_input():
    g = build_graph([])
    assert g.nodes == ()
    assert g.edges == ()


def test_build_graph_one_node_no_edges():
    g = build_graph([_m("alpha")])
    assert len(g.nodes) == 1
    assert g.nodes[0].name == "alpha"
    assert g.edges == ()


def test_build_graph_drops_external_deps():
    """deps to non-projects should NOT become edges."""
    g = build_graph([_m("alpha", deps=("requests", "pydantic"))])
    assert g.edges == ()


def test_build_graph_creates_edge_for_internal_dep():
    g = build_graph([
        _m("alpha", deps=("beta",)),
        _m("beta"),
    ])
    assert len(g.edges) == 1
    assert g.edges[0] == GraphEdge(src="alpha", dst="beta", dep_kind="dep")


def test_build_graph_skips_dev_deps_by_default():
    g = build_graph([
        _m("alpha", dev_deps=("beta",)),
        _m("beta"),
    ])
    assert g.edges == ()


def test_build_graph_includes_dev_deps_when_asked():
    g = build_graph(
        [_m("alpha", dev_deps=("beta",)), _m("beta")],
        include_dev_deps=True,
    )
    assert len(g.edges) == 1
    assert g.edges[0].dep_kind == "dev_dep"


def test_build_graph_no_self_loops():
    g = build_graph([_m("alpha", deps=("alpha",))])
    assert g.edges == ()


def test_build_graph_composer_alias_short_name():
    """composer's vendor/pkg should match a dep listed as `pkg` too."""
    g = build_graph([
        _m("user/utils", language="php"),
        _m("user/app", language="php", deps=("utils",)),
    ])
    # The bare-name alias maps "utils" → "user/utils"
    assert any(e.dst == "user/utils" for e in g.edges)


def test_build_graph_dedupes_duplicate_edges():
    """If a project lists the same dep twice (rare, but possible across
    parsing modes), the graph should still emit one edge."""
    m_alpha = _m("alpha", deps=("beta", "beta"))
    g = build_graph([m_alpha, _m("beta")])
    assert len(g.edges) == 1


def test_graph_node_as_dict_omits_optional_when_none():
    n = GraphNode(name="x", language="python", path="/p/x")
    d = n.as_dict()
    assert "version" not in d
    assert "description" not in d


def test_graph_node_as_dict_includes_optional_when_present():
    n = GraphNode(name="x", language="python", path="/p/x", version="1", description="d")
    d = n.as_dict()
    assert d["version"] == "1"
    assert d["description"] == "d"


def test_graph_as_dict_round_trip():
    g = ProjectGraph(
        nodes=(GraphNode(name="x", language="python", path="/p/x"),),
        edges=(GraphEdge(src="x", dst="y", dep_kind="dep"),),
    )
    d = g.as_dict()
    assert d["nodes"][0]["name"] == "x"
    assert d["edges"][0] == {"src": "x", "dst": "y", "kind": "dep"}


# --- Mermaid render -------------------------------------------------------


def test_mermaid_emits_graph_lr_header():
    out = graph_to_mermaid(ProjectGraph())
    assert out.startswith("graph LR")


def test_mermaid_emits_node_per_graphnode():
    g = build_graph([_m("alpha"), _m("beta")])
    out = graph_to_mermaid(g)
    assert 'alpha["alpha"]' in out
    assert 'beta["beta"]' in out


def test_mermaid_emits_solid_arrow_for_dep():
    g = build_graph([_m("alpha", deps=("beta",)), _m("beta")])
    out = graph_to_mermaid(g)
    assert "alpha --> beta" in out


def test_mermaid_emits_dotted_arrow_for_dev_dep():
    g = build_graph(
        [_m("alpha", dev_deps=("beta",)), _m("beta")],
        include_dev_deps=True,
    )
    out = graph_to_mermaid(g)
    assert "alpha -.-> beta" in out


def test_mermaid_sanitises_unsafe_chars_in_id():
    """composer's `vendor/pkg` and npm's `@scope/pkg` are not valid
    Mermaid ids — must be normalised."""
    m = ProjectManifest(
        name="vendor/app",
        language="php",
        path="/p/vendor-app",
        manifest_file="/p/vendor-app/composer.json",
    )
    g = build_graph([m])
    out = graph_to_mermaid(g)
    assert "vendor_app" in out
    # Original name preserved as the label:
    assert '"vendor/app"' in out
